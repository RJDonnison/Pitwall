"""Chronological, small-sample calibration of existing pre-weekend forecasts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

from .backtest import BacktestRow, run_backtest
from .data import DataError, season_weekends

MODEL_VERSION = 1
DEFAULT_MODEL_DIR = Path(".f1fantasy/models")


@dataclass(frozen=True)
class Observation:
    round: int
    kind: str
    session: str
    actual: float
    signals: tuple[float, ...]


def model_path(season: int, directory: Path = DEFAULT_MODEL_DIR) -> Path:
    return directory / f"{season}-calibration-v{MODEL_VERSION}.json"


def observations(
    risk_rows: list[BacktestRow], legacy_rows: list[BacktestRow]
) -> list[Observation]:
    """Align forecasts whose feature cutoffs precede the same target weekend."""
    if [r.weekend.round for r in risk_rows] != [r.weekend.round for r in legacy_rows]:
        raise DataError("Training forecast weekends are not aligned")
    output = []
    for newer, older in zip(risk_rows, legacy_rows):
        by_id = {asset.id: asset for asset in older.assets}
        for asset in newer.assets:
            before = by_id.get(asset.id)
            if (
                before is None
                or before.kind != asset.kind
                or before.actual != asset.actual
            ):
                raise DataError(f"Training forecast asset mismatch: {asset.name}")
            for session in (
                ("qualifying", "sprint", "race")
                if newer.weekend.sprint
                else ("qualifying", "race")
            ):
                target = getattr(asset.actual, session)
                modern = getattr(asset.predicted, session)
                old = getattr(before.predicted, session)
                signals = (
                    (
                        modern,
                        old,
                        asset.baseline_race_points
                        if asset.baseline_race_points is not None
                        else modern,
                    )
                    if session == "race"
                    else (modern, old)
                )
                if not all(isfinite(value) for value in (target, *signals)):
                    raise DataError(f"Invalid training score for {asset.name}")
                output.append(
                    Observation(
                        newer.weekend.round, asset.kind, session, target, signals
                    )
                )
    return output


def chronological_split(rounds: list[int]) -> tuple[list[int], list[int], list[int]]:
    unique = sorted(set(rounds))
    if len(unique) < 8:
        raise DataError("Need at least eight completed scoring weekends for training")
    train_end = ceil(len(unique) / 2)
    val_end = train_end + max(2, (len(unique) - train_end) // 2)
    if len(unique) - val_end < 2:
        raise DataError("Need at least two untouched test weekends")
    return unique[:train_end], unique[train_end:val_end], unique[val_end:]


def _fit(samples: list[Observation], count: int) -> list[float]:
    """Minimize absolute error with nonnegative weights and a baseline prior."""
    n = len(samples)
    objective = np.array([-0.3] + [0.0] * (count - 1) + [1 / n] * n)
    constraints, limits = [], []
    for index, sample in enumerate(samples):
        positive = list(sample.signals) + [0.0] * n
        positive[count + index] = -1
        negative = [-value for value in sample.signals] + [0.0] * n
        negative[count + index] = -1
        constraints.extend((positive, negative))
        limits.extend((sample.actual, -sample.actual))
    result = linprog(
        objective,
        A_ub=constraints,
        b_ub=limits,
        A_eq=[[1.0] * count + [0.0] * n],
        b_eq=[1.0],
        bounds=[(0, 1)] * count + [(0, None)] * n,
        method="highs",
    )
    if not result.success or result.x is None:
        raise DataError(f"Cannot fit model weights: {result.message}")
    return [float(weight) for weight in result.x[:count]]


def _mae(rows: list[Observation], weights: list[float]) -> float:
    return sum(
        abs(sum(w * signal for w, signal in zip(weights, item.signals)) - item.actual)
        for item in rows
    ) / len(rows)


def fit_calibration(items: list[Observation], season: int) -> dict:
    train, validation, test = chronological_split([item.round for item in items])
    report: dict = {
        "version": MODEL_VERSION,
        "season": season,
        "trained_rounds": train,
        "validation_rounds": validation,
        "test_rounds": test,
        "last_completed_round": test[-1],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights": {},
        "metrics": {},
        "active": False,
    }
    for kind in ("DRIVER", "CONSTRUCTOR"):
        report["weights"][kind] = {}
        report["metrics"][kind] = {}
        for session in ("qualifying", "sprint", "race"):
            selected = [
                item for item in items if item.kind == kind and item.session == session
            ]
            dimensions = 3 if session == "race" else 2
            default = [1.0] + [0.0] * (dimensions - 1)
            a = [item for item in selected if item.round in train]
            b = [item for item in selected if item.round in validation]
            c = [item for item in selected if item.round in test]
            # One or two Sprints are insufficient to learn a separate model.
            if (
                len({i.round for i in a}) < 3
                or len({i.round for i in b}) < 2
                or len({i.round for i in c}) < 2
            ):
                report["weights"][kind][session] = default
                report["metrics"][kind][session] = {
                    "reason": "insufficient weekends",
                    "promoted": False,
                    "samples": [len(a), len(b), len(c)],
                }
                continue
            candidate = _fit(a, dimensions)
            baseline_validation = _mae(b, default)
            candidate_validation = _mae(b, candidate)
            baseline_test = _mae(c, default)
            candidate_test = _mae(c, candidate)
            promote = (
                candidate_validation + 0.05 < baseline_validation
                and candidate_test + 0.05 < baseline_test
            )
            report["weights"][kind][session] = candidate if promote else default
            report["metrics"][kind][session] = {
                "candidate_weights": candidate,
                "promoted": promote,
                "samples": [len(a), len(b), len(c)],
                "validation": {
                    "baseline_mae": baseline_validation,
                    "candidate_mae": candidate_validation,
                },
                "test": {
                    "baseline_mae": baseline_test,
                    "candidate_mae": candidate_test,
                },
            }
            report["active"] |= promote
    return report


def load_model(season: int, directory: Path = DEFAULT_MODEL_DIR) -> dict | None:
    path = model_path(season, directory)
    if not path.exists():
        return None
    try:
        result = json.loads(path.read_text())
        if (
            result["version"] != MODEL_VERSION
            or result["season"] != season
            or not isinstance(result["active"], bool)
            or not isinstance(result["last_completed_round"], int)
        ):
            raise DataError("Invalid saved calibration metadata")
        for kind in ("DRIVER", "CONSTRUCTOR"):
            for session, size in (("qualifying", 2), ("sprint", 2), ("race", 3)):
                weights = result["weights"][kind][session]
                if (
                    len(weights) != size
                    or any(not isfinite(float(w)) or float(w) < 0 for w in weights)
                    or abs(sum(weights) - 1) > 1e-6
                ):
                    raise DataError("Invalid saved calibration weights")
        return result
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise DataError(f"Cannot verify saved model {path}: {exc}") from exc


def train(
    season: int,
    *,
    directory: Path = DEFAULT_MODEL_DIR,
    lookback: int = 5,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    complete = [
        w
        for w in season_weekends(season)
        if w.last_session is not None
        and w.last_session + timedelta(days=1) < now
        and w.round >= 5
    ]
    if len(complete) < 8:
        raise DataError(
            "At least eight finalized weekends after round four are required"
        )
    previous = load_model(season, directory)
    if previous is not None and previous["last_completed_round"] >= complete[-1].round:
        return previous
    current = run_backtest(
        season, count=len(complete), lookback=lookback, now=now, use_risk=True
    )
    legacy = run_backtest(
        season, count=len(complete), lookback=lookback, now=now, use_risk=False
    )
    report = fit_calibration(observations(current, legacy), season)
    path = model_path(season, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, allow_nan=False, indent=2) + "\n")
    temporary.replace(path)
    return report
