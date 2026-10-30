"""Pre-cutoff empirical weather analogues with forward-only promotion evidence."""

import numpy as np

from . import public_history

VERSION = "weather-analogue-v1"


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
    )
    racing = [
        r for r in document.get("racing", []) if public_history.date(r["end"]) < cutoff
    ]
    for asset in assets:
        scores = list(forecasts[asset.id])
        for i, kind in enumerate(("Q", "S", "R")):
            if kind == "S" and not weekend.sprint:
                continue
            all_values, conditioned = [], []
            for record in racing:
                days = [
                    day
                    for day, end in document.get("fantasy_events", {}).items()
                    if abs(
                        (
                            public_history.date(end)
                            - public_history.date(record["end"])
                        ).total_seconds()
                    )
                    < 43200
                ]
                if len(days) != 1:
                    continue
                row = next(
                    (
                        r
                        for r in document.get("fantasy", {}).get(days[0], [])
                        if str(r["PlayerId"]) == asset.id
                    ),
                    None,
                )
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
                        - float(row.get("SprintPoints") or 0)
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


def evaluation(settlements):
    groups = []
    for sprint in (False, True):
        for kind_index, kind in enumerate(("Q", "S", "R")):
            if kind == "S" and not sprint:
                continue
            pairs = []
            for row in settlements:
                model = row.get("weather_model") or {}
                if (
                    row["sprint"] != sprint
                    or model.get("model") != VERSION
                    or model.get("status") != "candidate"
                ):
                    continue
                errors = [
                    (
                        abs(model["forecasts"][a][kind_index] - y[kind_index]),
                        abs(row["forecasts"][a][kind_index] - y[kind_index]),
                    )
                    for a, y in row["actual"].items()
                    if a in model.get("forecasts", {}) and a in row["forecasts"]
                ]
                if errors:
                    pairs.append(np.mean(errors, axis=0))
            groups.append(
                {
                    "sprint": sprint,
                    "session": kind,
                    "weekends": len(pairs),
                    "candidate_mae": float(np.mean(pairs, axis=0)[0])
                    if pairs
                    else None,
                    "baseline_mae": float(np.mean(pairs, axis=0)[1]) if pairs else None,
                }
            )
    return {
        "model": VERSION,
        "status": "shadow",
        "groups": groups,
        "reason": "Candidate retained for chronological forward comparison; no improvement claimed or automatic promotion",
    }
