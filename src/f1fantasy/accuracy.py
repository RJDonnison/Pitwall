"""Forward accuracy and earlier-only, weekend-block conformal prediction ranges."""

import hashlib
import json
import math

import numpy as np

from . import public_history

VERSION = "forward-block-conformal-v1"


def identity(model):
    fantasy = model.get("fantasy", {})
    configuration = {
        "telemetry": model.get("telemetry"),
        "risk": model.get("risk"),
        "weather": model.get("weather"),
        "fantasy": fantasy.get("model"),
        "selected": {
            k: v.get("selected") for k, v in fantasy.get("groups", {}).items()
        },
    }
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode()
    ).hexdigest()[:16]


def baseline(assets, document, cutoff, sprint):
    """Last-three same-format official session means, frozen alongside forecasts."""
    days = []
    for day, end in document.get("fantasy_events", {}).items():
        if public_history.date(end) >= cutoff:
            continue
        matches = [
            r
            for r in document.get("racing", [])
            if public_history.date(r["end"]) < cutoff
            and abs(
                (
                    public_history.date(r["end"]) - public_history.date(end)
                ).total_seconds()
            )
            < 43200
        ]
        if len(matches) == 1 and ("S" in matches[0]["sessions"]) == sprint:
            days.append((end, day))
    result = {}
    for a in assets:
        values = []
        for _, day in sorted(days)[-3:]:
            row = next(
                (
                    r
                    for r in document["fantasy"].get(day, [])
                    if str(r["PlayerId"]) == a.id
                ),
                None,
            )
            try:
                q = float(row["QualifyingPoints"])
                s = float(row["SprintPoints"]) if sprint else 0.0
                r = float(row["GamedayPoints"]) - q - s
                if all(math.isfinite(v) for v in (q, s, r)):
                    values.append([q, s, r])
            except (KeyError, TypeError, ValueError):
                continue
        if values:
            result[a.id] = np.mean(values, axis=0).tolist()
    return result


def report(settlements, model, evaluated_at):
    fingerprint = identity(model)
    histories, grouped = [], {}
    for event in settlements:
        if identity(event["model"]) != fingerprint:
            continue
        for asset in event["assets"]:
            key = asset["id"]
            if key not in event["actual"] or key not in event["forecasts"]:
                continue
            for index, session in enumerate(("Q", "S", "R")):
                if session == "S" and not event["sprint"]:
                    continue
                group = f"{asset['kind']}/{session}/{'sprint' if event['sprint'] else 'regular'}"
                prediction, actual = (
                    event["forecasts"][key][index],
                    event["actual"][key][index],
                )
                prior = event.get("baseline", {}).get(key)
                interval = event.get("intervals", {}).get(key, {}).get(session)
                row = dict(
                    season=event["season"],
                    round=event["round"],
                    id=key,
                    name=asset["name"],
                    session=session,
                    group=group,
                    predicted=prediction,
                    actual=actual,
                    error=prediction - actual,
                    baseline=prior[index] if prior else None,
                    interval=interval,
                    generated_at=event["generated_at"],
                    completed_at=event["completed_at"],
                    model=fingerprint,
                )
                histories.append(row)
                grouped.setdefault(group, []).append(row)
    groups = {}
    for key, rows in grouped.items():
        weekends = sorted({(r["season"], r["round"]) for r in rows})
        # A weekend is one calibration unit. Use its maximum absolute residual
        # to avoid treating correlated driver/constructor observations as IID.
        blocks = [
            max(abs(r["error"]) for r in rows if (r["season"], r["round"]) == w)
            for w in weekends
        ]
        radius = (
            sorted(blocks)[min(len(blocks) - 1, math.ceil((len(blocks) + 1) * 0.8) - 1)]
            if len(blocks) >= 8
            else None
        )
        covered = [r for r in rows if r["interval"]]
        heldout_weekends = {(r["season"], r["round"]) for r in covered}
        hits = sum(
            r["interval"]["low"] <= r["actual"] <= r["interval"]["high"]
            for r in covered
        )
        paired = [r for r in rows if r["baseline"] is not None]
        groups[key] = dict(
            observations=len(rows),
            weekends=len(weekends),
            radius=radius,
            mae=float(np.mean([abs(r["error"]) for r in rows])),
            baseline_mae=float(
                np.mean([abs(r["baseline"] - r["actual"]) for r in paired])
            )
            if paired
            else None,
            paired_model_mae=float(np.mean([abs(r["error"]) for r in paired]))
            if paired
            else None,
            paired_observations=len(paired),
            coverage_hits=hits,
            coverage_observations=len(covered),
            coverage_weekends=len(heldout_weekends),
            confidence="Insufficient history"
            if radius is None
            else "Provisional range"
            if len(heldout_weekends) < 8
            else "Forward checked",
        )
    return dict(
        version=VERSION,
        model=fingerprint,
        evaluated_at=evaluated_at.isoformat(),
        status="ready" if histories else "insufficient_history",
        groups=groups,
        history=histories,
        baseline="Last three completed same-format official Fantasy weekends",
        definitions={
            "Insufficient history": "Fewer than eight archived weekends for this model, population, session and format; no prediction range.",
            "Provisional range": "At least eight earlier archived weekends; insufficient later weekends to check range coverage.",
            "Forward checked": "Range coverage measured on at least eight later weekends. This describes evidence depth, not a guarantee of accuracy.",
        },
        team_uncertainty="Unavailable: individual error bars cannot be added to obtain team, transfer or chip uncertainty",
    )


def intervals(assets, forecasts, sprint, accuracy):
    result = {}
    for a in assets:
        result[a.id] = {}
        for index, session in enumerate(("Q", "S", "R")):
            if session == "S" and not sprint:
                continue
            group = accuracy["groups"].get(
                f"{a.kind}/{session}/{'sprint' if sprint else 'regular'}", {}
            )
            radius = group.get("radius")
            if radius is not None:
                result[a.id][session] = dict(
                    low=forecasts[a.id][index] - radius,
                    high=forecasts[a.id][index] + radius,
                    method=VERSION,
                    calibration_weekends=group["weekends"],
                    confidence=group["confidence"],
                )
    return result
