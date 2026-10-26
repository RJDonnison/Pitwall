"""Separate probability and conditional-finish calibration for race scores."""

from __future__ import annotations

from dataclasses import dataclass

from .feature_training import Example


@dataclass(frozen=True)
class Components:
    probability_scale: float = 1.0
    classified_bias: float = 0.0


def fit(samples: list[Example]) -> Components:
    races = [item for item in samples if item.kind == "DRIVER" and item.phase == "race"]
    if not races:
        return Components()
    sources = {"fastf1_proxy": 0.2, "imported_official": 0.65, "current_official": 1.0}
    weights = [sources[item.source] for item in races]
    severe = [float(item.actual <= -20) for item in races]
    observed = (1 + sum(weight * flag for weight, flag in zip(weights, severe))) / (
        10 + sum(weights)
    )
    original = max(
        0.03,
        sum(weight * item.vector[7] for weight, item in zip(weights, races))
        / sum(weights),
    )
    scale = max(0.5, min(2.0, observed / original))
    classified = [
        (item.actual - (item.baseline + item.vector[8] * 20), weight)
        for item, weight in zip(races, weights)
        if item.actual > -20
    ]
    correction = (
        (
            sum(value * weight for value, weight in classified)
            / (8 + sum(weight for _, weight in classified))
        )
        if classified
        else 0.0
    )
    return Components(scale, max(-5.0, min(5.0, correction)))


def predict(item: Example, model: Components) -> tuple[float, float, float]:
    probability = max(0.0, min(0.5, item.vector[7] * model.probability_scale))
    conditional = item.baseline + item.vector[8] * 20 + model.classified_bias
    forecast = (1 - probability) * conditional - probability * 20
    forecast = item.baseline + max(-8, min(8, forecast - item.baseline))
    return forecast, probability, conditional


def apply(baseline: float, features: dict[str, float], weights: dict) -> float:
    from .feature_training import vector

    example = Example(0, "DRIVER", "race", 0.0, baseline, vector(features))
    return predict(example, Components(**weights))[0]


def replay(prior: list[Example], current: list[Example]) -> dict:
    pool = list(prior)
    rounds = sorted({item.round for item in current})
    weekly = []
    for round_number in rounds:
        race = [
            item
            for item in current
            if item.round == round_number
            and item.kind == "DRIVER"
            and item.phase == "race"
        ]
        if race:
            model = fit(pool)
            outputs = [predict(item, model) for item in race]
            baseline = sum(abs(item.baseline - item.actual) for item in race) / len(
                race
            )
            candidate = sum(
                abs(value - item.actual) for item, (value, _, _) in zip(race, outputs)
            ) / len(race)
            brier_base = sum(
                (item.vector[7] - float(item.actual <= -20)) ** 2 for item in race
            ) / len(race)
            brier_new = sum(
                (probability - float(item.actual <= -20)) ** 2
                for item, (_, probability, _) in zip(race, outputs)
            ) / len(race)
            classified = [
                (item, outputs[index][2])
                for index, item in enumerate(race)
                if item.actual > -20
            ]
            finish_base = (
                sum(
                    abs(item.baseline + item.vector[8] * 20 - item.actual)
                    for item, _ in classified
                )
                / len(classified)
                if classified
                else None
            )
            finish_new = (
                sum(abs(value - item.actual) for item, value in classified)
                / len(classified)
                if classified
                else None
            )
            weekly.append(
                {
                    "round": round_number,
                    "baseline_mae": baseline,
                    "component_mae": candidate,
                    "baseline_brier": brier_base,
                    "calibrated_brier": brier_new,
                    "baseline_classified_mae": finish_base,
                    "calibrated_classified_mae": finish_new,
                    "prior_examples": len(
                        [
                            item
                            for item in pool
                            if item.kind == "DRIVER" and item.phase == "race"
                        ]
                    ),
                }
            )
        pool.extend(item for item in current if item.round == round_number)
    if not weekly:
        return {
            "component_active": False,
            "component_weights": {"probability_scale": 1.0, "classified_bias": 0.0},
            "component_metrics": {"reason": "no driver races"},
            "component_weekly": [],
        }
    avg = lambda rows, key: sum(row[key] for row in rows) / len(rows)
    recent = weekly[len(weekly) // 2 :]
    baseline, candidate = avg(weekly, "baseline_mae"), avg(weekly, "component_mae")
    active = (
        len(weekly) >= 5
        and candidate + 0.05 < baseline
        and avg(recent, "component_mae") + 0.05 < avg(recent, "baseline_mae")
        and avg(weekly, "calibrated_brier") <= avg(weekly, "baseline_brier") + 0.01
    )
    weights = fit(pool) if active else Components()
    return {
        "component_active": active,
        "component_weights": vars(weights),
        "component_weekly": weekly,
        "component_metrics": {
            "promoted": active,
            "baseline_race_mae": baseline,
            "component_race_mae": candidate,
            "baseline_brier": avg(weekly, "baseline_brier"),
            "calibrated_brier": avg(weekly, "calibrated_brier"),
            "baseline_classified_mae": avg(
                [w for w in weekly if w["baseline_classified_mae"] is not None],
                "baseline_classified_mae",
            )
            if any(w["baseline_classified_mae"] is not None for w in weekly)
            else None,
            "calibrated_classified_mae": avg(
                [w for w in weekly if w["calibrated_classified_mae"] is not None],
                "calibrated_classified_mae",
            )
            if any(w["calibrated_classified_mae"] is not None for w in weekly)
            else None,
        },
    }
