"""Pre-cutoff weather adjustments and paired forward-only accuracy evidence."""

import numpy as np

from . import public_history
from .accuracy import identity

VERSION = "weather-analogue-v2"


def classify(probability):
    return "dry" if probability < 30 else "wet" if probability >= 70 else "changeable"


def candidate(assets, weekend, forecasts, weather, document, cutoff):
    result = {
        "model": VERSION,
        "status": "unavailable",
        "applied": False,
        "reason": "No verified pre-weekend weather forecast",
        "samples": {},
    }
    if (
        weather.get("status") != "available"
        or not public_history.date(weather["fetched_at"])
        <= cutoff
        < weekend.first_session
    ):
        return result
    condition = classify(weather["daily_rain_probability_max"])
    regime = {"dry": "dry", "wet": "wet", "changeable": "mixed"}[condition]
    result.update(
        status="candidate",
        condition=condition,
        reason="Experimental daily-weather analogue; forward evidence required",
        forecasts={},
        baseline_forecasts={key: list(value) for key, value in forecasts.items()},
    )
    racing = [
        r
        for r in document.get("racing", [])
        if public_history.date(r["end"]) < cutoff
        and ("S" in r.get("sessions", {})) == weekend.sprint
    ]
    samples = []
    for record in racing:
        days = [
            day
            for day, end in document.get("fantasy_events", {}).items()
            if public_history.date(end) < cutoff
            and abs(
                (
                    public_history.date(end) - public_history.date(record["end"])
                ).total_seconds()
            )
            < 43200
        ]
        if len(days) != 1:
            continue
        samples.append(
            (
                record,
                {
                    str(r["PlayerId"]): r
                    for r in document.get("fantasy", {}).get(days[0], [])
                },
            )
        )
    for asset in assets:
        scores = list(forecasts[asset.id])
        for i, kind in enumerate(("Q", "S", "R")):
            if kind == "S" and not weekend.sprint:
                continue
            all_values, conditioned = [], []
            for record, rows in samples:
                if kind not in record.get("sessions", {}):
                    continue
                row = rows.get(asset.id)
                if row is None:
                    continue
                try:
                    value = float(
                        row["QualifyingPoints"]
                        if kind == "Q"
                        else row["SprintPoints"]
                        if kind == "S"
                        else float(row["GamedayPoints"])
                        - float(row["QualifyingPoints"])
                        - (float(row["SprintPoints"]) if weekend.sprint else 0)
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if not np.isfinite(value):
                    continue
                all_values.append(value)
                if (
                    record.get("session_context", {}).get(kind, {}).get("regime")
                    == regime
                ):
                    conditioned.append(value)
            result["samples"][f"{asset.id}/{kind}"] = len(conditioned)
            if len(conditioned) >= 3:
                # Shrink sparse conditional differences, retaining official pace,
                # incidents and reliability contributions in the session labels.
                scores[i] += (
                    len(conditioned)
                    / (len(conditioned) + 8)
                    * (float(np.mean(conditioned)) - float(np.mean(all_values)))
                )
        result["forecasts"][asset.id] = scores
    return result


def evaluation(settlements, configuration=None):
    groups = []
    for population in ("DRIVER", "CONSTRUCTOR"):
        for sprint in (False, True):
            for kind_index, kind in enumerate(("Q", "S", "R")):
                if kind == "S" and not sprint:
                    continue
                pairs = []
                for row in settlements:
                    model = row.get("weather_model") or {}
                    if (
                        row["sprint"] != sprint
                        or (
                            configuration is not None
                            and identity(row["model"]) != identity(configuration)
                        )
                        or model.get("model") != VERSION
                        or model.get("status")
                        not in {"candidate", "selected", "insufficient_history"}
                        or "baseline_forecasts" not in model
                    ):
                        continue
                    baseline = model["baseline_forecasts"]
                    eligible = {
                        a["id"] for a in row["assets"] if a["kind"] == population
                    }
                    errors = [
                        (
                            abs(model["forecasts"][a][kind_index] - y[kind_index]),
                            abs(baseline[a][kind_index] - y[kind_index]),
                        )
                        for a, y in row["actual"].items()
                        if a in eligible
                        and a in model.get("forecasts", {})
                        and a in baseline
                    ]
                    if errors:
                        pairs.append(np.mean(errors, axis=0))
                groups.append(
                    {
                        "sprint": sprint,
                        "kind": population,
                        "session": kind,
                        "weekends": len(pairs),
                        "candidate_mae": float(np.mean(pairs, axis=0)[0])
                        if pairs
                        else None,
                        "baseline_mae": float(np.mean(pairs, axis=0)[1])
                        if pairs
                        else None,
                    }
                )
    return {
        "model": VERSION,
        "status": "forward_evaluation",
        "groups": groups,
        "reason": "Paired archived weather-adjusted and weather-free forecasts; no improvement claimed before finalized forward evidence",
    }
