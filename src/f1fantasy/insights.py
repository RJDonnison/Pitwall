"""Public Race Insights: observed results and uncalibrated joint racing draws.

Fantasy scores never enter FIA point totals. Historical participants retain their
earned points even when they are no longer eligible for the Fantasy roster.
"""

from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import re

import numpy as np

from . import predict_data, predict_model, public_history
from .data import DataError
from .telemetry_model import adjustments

MODEL = "joint-racing-rank-bootstrap-prior-v1/insights-v1"


def refresh_pitstops(document, season, cutoff):
    """Archive finalized official stationary-stop winners with publication dates."""
    config = predict_data.get("apps/web_config.json")
    if int(config["currentSeasonYear"]) != season:
        raise DataError("Pit-stop source season disagrees with requested season")
    fixtures = predict_data.value(predict_data.get("schedule/raceday_en.json"))
    days = sorted(
        {
            int(r["GamedayId"])
            for r in fixtures
            if int(r["Season"]) == season
            and not int(r["IsBonusRound"])
            and not int(r["IsPostponed"])
            and int(r["MatchStatus"]) == 4
            and predict_data.utc(r["SessionEndDateISO8601"]) < cutoff
        }
    )[-8:]
    rows = []
    for day in days:
        body = predict_data.get(f"questions/questions_{day}_en.json")
        published = datetime.strptime(
            body["Meta"]["Timestamp"]["UTCTime"], "%m/%d/%Y %I:%M:%S %p"
        ).replace(tzinfo=timezone.utc)
        if published >= cutoff:
            continue
        winners = [
            q
            for q in predict_data.value(body)["Questions"]
            if re.search(r"fastest pit\s?stop", q["Text"], re.I)
            and int(q["Status"]) == 4
            and len(q["Answer"]) == 1
            and int(q["Answer"][0]["Type"]) == 2
        ]
        if len(winners) != 1:
            continue
        q = winners[0]
        winner = str(q["Answer"][0]["Id"])
        options = [
            o for o in q["Options"] if str(o["Id"]) == winner and int(o["Type"]) == 2
        ]
        if len(options) != 1:
            continue
        rows.append(
            {
                "season": season,
                "gameday_id": day,
                "team_name": str(options[0]["Value"]),
                "published_at": published.isoformat(),
                "completed_at": max(
                    predict_data.utc(r["SessionEndDateISO8601"])
                    for r in fixtures
                    if int(r["GamedayId"]) == day
                ).isoformat(),
            }
        )
    document["pitstop_winners"] = rows
    document["pitstop_checked_at"] = cutoff.isoformat()


def _normal(value):
    return "".join(c for c in value.casefold() if c.isalnum())


def _team_key(name):
    # Explicit source-name aliases, never substring/fuzzy attribution.
    aliases = {
        "oracleredbullracing": "redbullracing",
        "redbull": "redbullracing",
        "scuderiaferrari": "ferrari",
        "mclarenf1team": "mclaren",
        "haas": "haasf1team",
        "tgrhaasf1team": "haasf1team",
        "visacashappracingbulls": "racingbulls",
        "astonmartinaramco": "astonmartin",
    }
    key = _normal(name)
    return aliases.get(key, key)


def _statistics(records, season, assets, document, cutoff):
    selected = [r for r in records if r["season"] == season]
    drivers = {a.tla: a for a in assets if a.kind == "DRIVER"}
    teams = {_team_key(a.name): a for a in assets if a.kind == "CONSTRUCTOR"}
    populations = {"drivers": {}, "constructors": {}}

    def entry(kind, key, name, asset):
        return populations[kind].setdefault(
            key,
            {
                "key": key,
                "name": name,
                "asset_id": asset.id if asset else None,
                "races": 0,
                "entries": 0,
                "classified": 0,
                "wins": 0,
                "podiums": 0,
                "poles": 0,
                "sprint_entries": 0,
                "sprint_wins": 0,
                "points": 0.0,
                "points_complete": True,
            },
        )

    for record in selected:
        seen = set()
        for kind in ("R", "S", "Q"):
            for row in record["sessions"].get(kind, []):
                tla, name = row["tla"], row["team_name"]
                team_key = _team_key(name)
                driver = drivers.get(tla)
                constructor = teams.get(team_key)
                pair = [
                    entry("drivers", tla, driver.name if driver else tla, driver),
                    entry(
                        "constructors",
                        team_key,
                        constructor.name if constructor else name,
                        constructor,
                    ),
                ]
                for target in pair:
                    if kind in ("R", "S"):
                        if row.get("points") is None:
                            target["points_complete"] = False
                        else:
                            target["points"] += row["points"]
                    position = row.get("position")
                    if kind == "R":
                        target["entries"] += 1
                        target["classified"] += int(row["classified"])
                        target["wins"] += int(position == 1 and row["classified"])
                        target["podiums"] += int(
                            position is not None and position <= 3 and row["classified"]
                        )
                    elif kind == "S":
                        target["sprint_entries"] += 1
                        target["sprint_wins"] += int(
                            position == 1 and row["classified"]
                        )
                    else:
                        target["poles"] += int(
                            position == 1 and row.get("qualified", True)
                        )
                if kind == "R":
                    pair[0]["races"] += 1
                    seen.add(team_key)
        for key in seen:
            populations["constructors"][key]["races"] += 1
    expected = sorted(
        int(e["RoundNumber"])
        for key, e in document.get("events", {}).items()
        if key.startswith(f"{season}/")
        and public_history.date(e["race_start"]) + timedelta(hours=6) < cutoff
    )
    covered = sorted(r["round"] for r in selected)
    sprint_complete = all(
        r["sessions"].get("S")
        for r in selected
        if "sprint"
        in document.get("events", {})
        .get(f"{season}/{r['round']}", {})
        .get("EventFormat", "")
    )
    complete = (
        bool(expected)
        and covered == expected
        and sprint_complete
        and all(r["sessions"].get("R") and r["sessions"].get("Q") for r in selected)
    )
    return {
        "season": season,
        "rounds": covered,
        "expected_rounds": expected,
        "complete": bool(complete),
        **{
            kind: sorted(rows.values(), key=lambda r: (-r["points"], r["name"]))
            for kind, rows in populations.items()
        },
    }


def _pitstops(document, assets, cutoff, season):
    teams = [a for a in assets if a.kind == "CONSTRUCTOR"]
    rows = [
        r
        for r in document.get("pitstop_winners", [])
        if r["season"] == season
        and public_history.date(r["published_at"]) < cutoff
        and public_history.date(r["completed_at"]) < cutoff
    ][-8:]
    counts = Counter(_team_key(r["team_name"]) for r in rows)
    known = {_team_key(a.name) for a in teams}
    if not rows or counts.keys() - known:
        return {
            "status": "unavailable",
            "message": "No verified pre-cutoff stationary-stop winners matching this roster. Refresh public history.",
        }
    return {
        "status": "ready",
        "samples": len(rows),
        "prior_per_team": 1,
        "checked_at": document.get("pitstop_checked_at"),
        "evidence": rows,
        "source": "https://f1predict.formula1.com/",
        "probabilities": {
            a.id: (1 + counts[_team_key(a.name)]) / (len(teams) + len(rows))
            for a in teams
        },
    }


def _summary(observed, draws):
    final = draws + observed
    return {
        "observed": float(observed),
        "remaining": float(draws.mean()),
        "projected": float(final.mean()),
        "interval80": np.quantile(final, [0.1, 0.9]).tolist(),
    }


def build(assets, weekends, cutoff, *, telemetry=True, simulations=4000, seed=2026):
    source = public_history.current()
    if not source:
        return {
            "status": "unavailable",
            "message": "Race Insights requires the public historical dataset.",
        }
    document = source["document"]
    try:
        return _build(document, assets, weekends, cutoff, telemetry, simulations, seed)
    except (DataError, KeyError, TypeError, ValueError) as exc:
        return {"status": "unavailable", "message": str(exc)}


def _build(document, assets, weekends, cutoff, telemetry, simulations, seed):
    if (
        simulations < 1
        or not weekends
        or cutoff > datetime.now(timezone.utc)
        or cutoff > weekends[0].first_session
    ):
        raise DataError("Race Insights requires a pre-weekend historical cutoff")
    season = weekends[0].season
    records = sorted(
        [
            r
            for r in document.get("racing", [])
            if public_history.date(r["end"]) < cutoff
        ],
        key=lambda r: public_history.date(r["end"]),
    )
    if len({(r["season"], r["round"]) for r in records}) != len(records):
        raise DataError("Duplicate racing history")
    if not records:
        raise DataError("No completed racing history before cutoff")
    history = [
        _statistics(records, year, assets, document, cutoff)
        for year in sorted({r["season"] for r in records}, reverse=True)
    ]
    current = next((h for h in history if h["season"] == season), None)
    drivers = [a for a in assets if a.kind == "DRIVER"]
    constructors = [a for a in assets if a.kind == "CONSTRUCTOR"]
    if (
        len(drivers) < 3
        or any(not a.tla for a in drivers)
        or len({a.tla for a in drivers}) != len(drivers)
    ):
        raise DataError("Race Insights requires unique driver identities")
    roster = [
        {"id": a.id, "name": a.name, "tla": a.tla, "team_id": a.team_id}
        for a in drivers
    ]
    # A single cutoff applies to every future round, including telemetry features.
    targets = [replace(w, first_session=cutoff) for w in weekends]
    deltas = adjustments(assets, targets) if telemetry else {}
    rng = np.random.default_rng(seed)
    totals = np.zeros((simulations, len(drivers)))
    team_totals = {a.id: np.zeros(simulations) for a in constructors}
    rounds = []
    for t, weekend in enumerate(weekends):
        draw = predict_model._draw(
            records,
            roster,
            simulations,
            rng,
            {(0, a.id): deltas.get((t, a.id), (0, 0, 0)) for a in drivers},
        )
        probabilities = {"drivers": {}, "constructors": {}}
        masks = {}
        for kind in ("R", "Q") + (("S",) if weekend.sprint else ()):
            ranks, classified = draw[kind]["ranks"], draw[kind]["classified"]
            if kind == "Q":
                masks["pole"] = (ranks == 1) & classified
                continue
            prefix = "sprint_" if kind == "S" else ""
            masks.update(
                {
                    prefix + "win": (ranks == 1) & classified,
                    prefix + "podium": (ranks <= 3) & classified,
                    prefix + "top10": (ranks <= 10) & classified,
                    prefix + "nc": ~classified,
                }
            )
            table = np.array(
                [0, 25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * len(drivers)
            )
            earned = (
                table[ranks] if kind == "R" else np.maximum(0, 9 - ranks)
            ) * classified
            totals += earned
            for a in constructors:
                indices = [i for i, d in enumerate(drivers) if d.team_id == a.team_id]
                if not indices:
                    raise DataError(f"No verified drivers for {a.name}")
                team_totals[a.id] += earned[:, indices].sum(axis=1)
        for i, a in enumerate(drivers):
            probabilities["drivers"][a.id] = {
                key: float(mask[:, i].mean()) for key, mask in masks.items()
            }
        for a in constructors:
            indices = [i for i, d in enumerate(drivers) if d.team_id == a.team_id]
            probabilities["constructors"][a.id] = {
                key: float(mask[:, indices].any(axis=1).mean())
                for key, mask in masks.items()
            }
        rounds.append({"round": weekend.round, **probabilities})
    championship = {
        "status": "unavailable",
        "message": "Complete current-season Race, Sprint and championship point coverage is required.",
    }
    if (
        current
        and current["complete"]
        and all(
            r["points_complete"]
            for kind in ("drivers", "constructors")
            for r in current[kind]
        )
    ):
        championship = {"status": "ready", "drivers": [], "constructors": []}
        for kind in ("drivers", "constructors"):
            active = {
                a.tla if kind == "drivers" else _team_key(a.name): a
                for a in (drivers if kind == "drivers" else constructors)
            }
            observed = {r["key"]: r for r in current[kind]}
            for key in observed.keys() | active.keys():
                a = active.get(key)
                row = observed.get(key)
                samples = (
                    (
                        totals[:, drivers.index(a)]
                        if kind == "drivers"
                        else team_totals[a.id]
                    )
                    if a
                    else np.zeros(simulations)
                )
                championship[kind].append(
                    {
                        "key": key,
                        "name": a.name if a else row["name"],
                        "asset_id": a.id if a else None,
                        **_summary(row["points"] if row else 0, samples),
                    }
                )
            championship[kind].sort(key=lambda r: (-r["projected"], r["name"]))
    return {
        "status": "ready",
        "model": MODEL,
        "cutoff": cutoff.isoformat(),
        "simulations": simulations,
        "seed": seed,
        "calibrated": False,
        "form_samples": {
            k: min(8, sum(bool(r["sessions"].get(k)) for r in records))
            for k in ("Q", "R", "S")
        },
        "historical_events": [
            {"season": r["season"], "round": r["round"], "end": r["end"]}
            for r in records
        ],
        "history": history,
        "rounds": rounds,
        "championship": championship,
        "pitstops": _pitstops(document, assets, cutoff, season),
    }
