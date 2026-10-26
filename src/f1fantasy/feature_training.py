"""Regularized, point-in-time correction using form, circuit and reliability."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np

from .backtest import BacktestRow
from .data import DataError

FEATURE_NAMES = (
    "bias",
    "fastf1_form",
    "official_form",
    "recent3",
    "team_form",
    "circuit_form",
    "telemetry_delta",
    "severe_probability",
    "classified_points",
)


@dataclass(frozen=True)
class Example:
    round: int
    kind: str
    phase: str
    actual: float
    baseline: float
    vector: tuple[float, ...]
    source: str = "current_official"


def vector(values: dict[str, float]) -> tuple[float, ...]:
    baseline = values["baseline"]
    scale = 20.0
    result = (
        1.0,
        (values["fastf1_form"] - baseline) / scale,
        (values["official_form"] - baseline) / scale,
        (values["recent3"] - baseline) / scale,
        (values["team_form"] - baseline) / scale,
        (values["circuit_form"] - baseline) / scale,
        values["telemetry_delta"] / 5.0,
        values["severe_probability"],
        (values["classified_points"] - baseline) / scale,
    )
    if not all(isfinite(value) for value in result):
        raise DataError("Non-finite training feature")
    return result


def from_backtests(rows: list[BacktestRow]) -> list[Example]:
    result = []
    for week in rows:
        for asset in week.assets:
            if asset.features is None:
                raise DataError("Forecast lacks pre-weekend training features")
            phases = (
                ("qualifying", "sprint", "race")
                if week.weekend.sprint
                else ("qualifying", "race")
            )
            for phase in phases:
                result.append(
                    Example(
                        week.weekend.round,
                        asset.kind,
                        phase,
                        getattr(asset.actual, phase),
                        getattr(asset.predicted, phase),
                        vector(asset.features[phase]),
                    )
                )
    return result


def prior_features(prior_observations: list) -> list[Example]:
    """Warm-start weak proxy features without pretending telemetry was measured."""
    examples = []
    for item in prior_observations:
        baseline = item.signals[0]
        previous = item.signals[1]
        recent = item.signals[2] if item.session == "race" else previous
        values = {
            "baseline": baseline,
            "fastf1_form": previous,
            "official_form": previous,
            "recent3": recent,
            "team_form": previous,
            "circuit_form": previous,
            "telemetry_delta": 0.0,
            "severe_probability": 0.0,
            "classified_points": previous,
        }
        examples.append(
            Example(
                item.round,
                item.kind,
                item.session,
                item.actual,
                baseline,
                vector(values),
                item.source,
            )
        )
    return examples


def fit(samples: list[Example]) -> list[float]:
    """Huber-weighted ridge fit; shrink hard toward the fixed forecast."""
    count = len(FEATURE_NAMES)
    if not samples or any(len(item.vector) != count for item in samples):
        raise DataError("Insufficient or invalid feature training examples")
    X = np.asarray([item.vector for item in samples], dtype=float)
    target = np.asarray([item.actual - item.baseline for item in samples], dtype=float)
    source = np.asarray(
        [
            {"fastf1_proxy": 0.2, "imported_official": 0.65, "current_official": 1.0}[
                item.source
            ]
            for item in samples
        ]
    )
    alpha = np.asarray([15.0] + [30.0] * (count - 1))
    coefficients = np.zeros(count)
    for _ in range(6):
        residual = target - X @ coefficients
        robust = np.minimum(1.0, 12.0 / np.maximum(np.abs(residual), 1e-6))
        weights = source * robust
        lhs = X.T @ (X * weights[:, None]) + np.diag(alpha)
        coefficients = np.linalg.solve(lhs, X.T @ (weights * target))
    coefficients = np.clip(coefficients, -8, 8)
    return [float(value) for value in coefficients]


def predict(item: Example, weights: list[float]) -> float:
    max_change = 8 if item.phase == "race" else 4
    correction = float(np.dot(weights, item.vector))
    return item.baseline + max(-max_change, min(max_change, correction))


def apply(
    baseline: float, feature_values: dict[str, float], phase: str, weights: list[float]
) -> float:
    example = Example(0, "DRIVER", phase, 0.0, baseline, vector(feature_values))
    return predict(example, weights)


def replay(prior: list[Example], current: list[Example]) -> dict:
    """Refit only after each round's forecasts have been scored."""
    pool = list(prior)
    rounds = sorted({item.round for item in current})
    weekly, metrics, coefficients = [], {}, {}
    errors: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for round_number in rounds:
        week = [item for item in current if item.round == round_number]
        measurements = {}
        for kind in ("DRIVER", "CONSTRUCTOR"):
            for phase in ("qualifying", "sprint", "race"):
                target = [
                    item for item in week if item.kind == kind and item.phase == phase
                ]
                if not target:
                    continue
                historic = [
                    item for item in pool if item.kind == kind and item.phase == phase
                ]
                available = len({item.round for item in historic}) >= (
                    3 if phase == "sprint" else 5
                )
                weights = fit(historic) if available else [0.0] * len(FEATURE_NAMES)
                plain = sum(abs(item.baseline - item.actual) for item in target) / len(
                    target
                )
                trained = sum(
                    abs(predict(item, weights) - item.actual) for item in target
                ) / len(target)
                errors.setdefault((kind, phase), []).append((plain, trained))
                measurements[f"{kind}.{phase}"] = {
                    "baseline_mae": plain,
                    "feature_mae": trained,
                    "prior_examples": len(historic),
                }
        weekly.append({"round": round_number, "errors": measurements})
        pool.extend(week)
    active = False
    for kind in ("DRIVER", "CONSTRUCTOR"):
        coefficients[kind], metrics[kind] = {}, {}
        for phase in ("qualifying", "sprint", "race"):
            group = errors.get((kind, phase), [])
            old = sum(b for b, _ in group) / len(group) if group else None
            new = sum(m for _, m in group) / len(group) if group else None
            recent = group[len(group) // 2 :]
            promoted = (
                len(group) >= (3 if phase == "sprint" else 5)
                and new + 0.05 < old
                and sum(m for _, m in recent) / len(recent) + 0.05
                < sum(b for b, _ in recent) / len(recent)
            )
            coefficients[kind][phase] = (
                fit(
                    [item for item in pool if item.kind == kind and item.phase == phase]
                )
                if promoted
                else [0.0] * len(FEATURE_NAMES)
            )
            metrics[kind][phase] = {
                "weekends": len(group),
                "baseline_mae": old,
                "feature_mae": new,
                "promoted": promoted,
            }
            active |= promoted
    return {
        "feature_names": list(FEATURE_NAMES),
        "feature_weights": coefficients,
        "feature_metrics": metrics,
        "feature_weekly": weekly,
        "feature_active": active,
    }
