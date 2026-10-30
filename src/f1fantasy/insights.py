"""Public Race Insights: observed results and uncalibrated joint racing draws.

Fantasy scores never enter FIA point totals. Historical participants retain their
earned points even when they are no longer eligible for the Fantasy roster.
"""

from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import re

import numpy as np

from . import predict_data, predict_model, public_history, racing_model, pitstop_model
from .data import DataError
from .telemetry_model import adjustments

MODEL = "timing-team-regime-walkforward-v2/insights-v2"


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
    )
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
    previous = {
        (r["season"], r["gameday_id"]): r for r in document.get("pitstop_winners", [])
    }
    for row in rows:
        key = row["season"], row["gameday_id"]
        if key not in previous or previous[key]["team_name"] != row["team_name"]:
            previous[key] = row
    document["pitstop_winners"] = [previous[k] for k in sorted(previous)]
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
        "kicksauber": "audi",
        "stakef1teamkicksauber": "audi",
        "alfaromeo": "audi",
        "rb": "racingbulls",
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
    timed = pitstop_model.forecast(document, assets, cutoff, season, _team_key)
    if timed is not None and timed["status"] == "ready":
        return timed
    teams = [a for a in assets if a.kind == "CONSTRUCTOR"]
    rows = [
        r
        for r in document.get("pitstop_winners", [])
        if season - 2 <= r["season"] <= season
        and public_history.date(r["published_at"]) < cutoff
        and public_history.date(r["completed_at"]) < cutoff
    ]
    counts = Counter(_team_key(r["team_name"]) for r in rows)
    known = {_team_key(a.name) for a in teams}
    if not rows or counts.keys() - known:
        return {
            "status": "unavailable",
            "message": "No verified pre-cutoff stationary-stop winners matching this roster. Refresh public history.",
        }
    weights = {a.id: 1.0 for a in teams}
    for index, row in enumerate(sorted(rows, key=lambda r: r["completed_at"])):
        for a in teams:
            if _team_key(a.name) == _team_key(row["team_name"]):
                weights[a.id] += 2 ** (-(len(rows) - index - 1) / 8)
    return {
        "status": "ready",
        "model": "time-decayed-finalized-winner-prior-v2",
        "timing_evaluation": timed.get("evaluation") if timed else None,
        "samples": len(rows),
        "prior_per_team": 1,
        "checked_at": document.get("pitstop_checked_at"),
        "evidence": rows,
        "source": "https://f1predict.formula1.com/",
        "probabilities": {a.id: weights[a.id] / sum(weights.values()) for a in teams},
    }


def _summary(observed, draws):
    final = draws + observed
    return {
        "observed": float(observed),
        "remaining": float(draws.mean()),
        "projected": float(final.mean()),
        "interval80": np.quantile(final, [0.1, 0.9]).tolist(),
    }


def _placements(draw, index):
    result = {}
    for kind in ("Q", "R", "S"):
        if kind not in draw:
            continue
        ranks = draw[kind]["ranks"][:, index]
        classified = draw[kind]["classified"][:, index]
        finishers = ranks[classified]
        result[kind] = {
            "mean": float(finishers.mean()) if len(finishers) else None,
            "interval80": [float(v) for v in np.quantile(finishers, [0.1, 0.9])]
            if len(finishers)
            else None,
            "positions": [
                float(((ranks == p) & classified).mean())
                for p in range(1, draw[kind]["ranks"].shape[1] + 1)
            ],
            "nc": float((~classified).mean()),
        }
    return result


def _championship_after(
    current, drivers, constructors, totals, team_totals, before, team_before
):
    if (
        not current
        or not current["complete"]
        or any(
            not row["points_complete"]
            for kind in ("drivers", "constructors")
            for row in current[kind]
        )
    ):
        return {"status": "unavailable"}
    result = {"status": "ready", "drivers": {}, "constructors": {}}
    for kind, assets in (("drivers", drivers), ("constructors", constructors)):
        observed = {row["key"]: row["points"] for row in current[kind]}
        active = {a.tla if kind == "drivers" else _team_key(a.name): a for a in assets}
        keys = sorted(observed.keys() | active.keys())
        samples, previous = {}, {}
        for key in keys:
            asset = active.get(key)
            gain = (
                (
                    totals[:, drivers.index(asset)]
                    if kind == "drivers"
                    else team_totals[asset.id]
                )
                if asset
                else np.zeros(len(totals))
            )
            prior = (
                (
                    before[:, drivers.index(asset)]
                    if kind == "drivers"
                    else team_before[asset.id]
                )
                if asset
                else np.zeros(len(totals))
            )
            samples[key] = observed.get(key, 0) + gain
            previous[key] = observed.get(key, 0) + prior
        field = np.column_stack([samples[key] for key in keys])
        for key, asset in active.items():
            final = samples[key]
            # Equal points share a position; do not invent official countback wins.
            ranks = 1 + (field > final[:, None]).sum(axis=1)
            result[kind][asset.id] = {
                "points": float(final.mean()),
                "points_before": float(previous[key].mean()),
                "round_points": float((final - previous[key]).mean()),
                "points_interval80": np.quantile(final, [0.1, 0.9]).tolist(),
                "standing_mean": float(ranks.mean()),
                "standing_interval80": np.quantile(ranks, [0.1, 0.9]).tolist(),
            }
    return result


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


def _title_eligibility(championship, records, assets, weekends):
    """Exclude impossible titles; retain exact unresolved countback ties."""
    races, sprints = len(weekends), sum(w.sprint for w in weekends)
    current = [r for r in records if r["season"] == weekends[0].season]
    positions = max(2, *(len(r["sessions"]["R"]) for r in current))
    drivers = [a for a in assets if a.kind == "DRIVER"]
    for kind in ("drivers", "constructors"):
        rows = championship[kind]
        finishes = {r["key"]: Counter() for r in rows}
        countback_complete = True
        for record in current:
            for result in record["sessions"]["R"]:
                if not result["classified"]:
                    continue
                position = result.get("position")
                if (
                    position is None
                    or not 1 <= position <= positions
                    or int(position) != position
                ):
                    countback_complete = False
                    continue
                key = (
                    result["tla"]
                    if kind == "drivers"
                    else _team_key(result["team_name"])
                )
                finishes[key][int(position)] += 1
        leader = max(r["observed"] for r in rows)
        for row in rows:
            a = next((a for a in assets if a.id == row["asset_id"]), None)
            cars = (
                (
                    1
                    if kind == "drivers"
                    else min(2, sum(d.team_id == a.team_id for d in drivers))
                )
                if a
                else 0
            )
            maximum = races * sum([25, 18][:cars]) + sprints * sum([8, 7][:cars])
            best = finishes[row["key"]].copy()
            for position in range(1, cars + 1):
                best[position] += races
            ceiling = row["observed"] + maximum
            loses_countback = (
                ceiling == leader
                and countback_complete
                and any(
                    rival["observed"] == leader
                    and tuple(best[p] for p in range(1, positions + 1))
                    < tuple(finishes[rival["key"]][p] for p in range(1, positions + 1))
                    for rival in rows
                    if rival is not row
                )
            )
            row.update(
                max_remaining=maximum,
                max_final=ceiling,
                title_eligible=ceiling >= leader and not loses_countback,
            )


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
        {
            "id": a.id,
            "name": a.name,
            "tla": a.tla,
            "team_id": a.team_id,
            "season": season,
        }
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
        before = totals.copy()
        team_before = {key: value.copy() for key, value in team_totals.items()}
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
        placements = {
            a.id: _placements(
                {k: draw[k] for k in ("Q", "R") + (("S",) if weekend.sprint else ())}, i
            )
            for i, a in enumerate(drivers)
        }
        rounds.append(
            {
                "round": weekend.round,
                **probabilities,
                "placements": placements,
                "championship_after": _championship_after(
                    current,
                    drivers,
                    constructors,
                    totals,
                    team_totals,
                    before,
                    team_before,
                ),
            }
        )
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
        _title_eligibility(championship, records, assets, weekends)
    return {
        "status": "ready",
        "model": MODEL,
        "model_selection": racing_model.selection(records),
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
