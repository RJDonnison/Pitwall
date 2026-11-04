"""Additional regular-round predicates over shared racing draws and sourced facts."""

import re

import numpy as np

from . import predict_evidence


def _yes_no(options, value, text):
    return [
        value
        if text(o["name"]) == "yes"
        else ~value
        if text(o["name"]) == "no"
        else None
        for o in options
    ]


def _teams(options, snapshot):
    from .insights import _team_key

    teams = []
    for option in options:
        matches = {
            str(row["team_id"])
            for row in snapshot["roster"]
            if int(row["kind"]) == 2
            and (
                (
                    int(option.get("kind", 0)) == 2
                    and str(row["id"]) == str(option["id"])
                )
                or _team_key(row["name"]) == _team_key(option["name"])
            )
        }
        teams.append(next(iter(matches)) if len(matches) == 1 else None)
    return teams


def _team_mask(drivers, team_id):
    return [str(driver["team_id"]) == team_id for driver in drivers]


def _points(draws, sprint):
    n = draws["R"]["ranks"].shape[1]
    points = np.array([0, 25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * n)
    result = points[draws["R"]["ranks"]] * draws["R"]["classified"]
    if sprint:
        result += np.maximum(0, 9 - draws["S"]["ranks"]) * draws["S"]["classified"]
    return result.astype(float)


def _standings(snapshot, drivers, draws, records, include_weekend=True):
    from .insights import _team_key

    # Replaced drivers retain their official season points and countback, but
    # cannot earn future points in the current round's verified active roster.
    historical = [r for r in records if int(r["season"]) == int(snapshot["season"])]
    tlas = list(
        dict.fromkeys(
            [d["tla"] for d in drivers]
            + [
                row["tla"]
                for r in historical
                for k in ("R", "S")
                for row in r["sessions"].get(k, [])
            ]
        )
    )
    scores = np.zeros((len(draws["R"]["ranks"]), len(tlas)))
    counts = np.zeros((*scores.shape, len(drivers)), dtype=int)
    teams = list(dict.fromkeys(str(d["team_id"]) for d in drivers))
    team_scores = np.zeros((len(scores), len(teams)))
    team_counts = np.zeros((len(scores), len(teams), len(drivers)), dtype=int)
    names = {}
    for row in snapshot["roster"]:
        name = row["name"] if int(row["kind"]) == 2 else row.get("team_name", "")
        names.setdefault(_team_key(name), set()).add(str(row["team_id"]))
    by_tla = {tla: i for i, tla in enumerate(tlas)}
    error = None
    for record in historical:
        for kind in ("R", "S"):
            for row in record["sessions"].get(kind, []):
                if row.get("points") is None:
                    return None, "Official historical championship points incomplete"
                i = by_tla[row["tla"]]
                scores[:, i] += row["points"]
                team = names.get(_team_key(row.get("team_name", "")), set())
                ti = (
                    teams.index(next(iter(team)))
                    if len(team) == 1 and next(iter(team)) in teams
                    else None
                )
                if ti is None:
                    error = (
                        "Historical constructor attribution is incomplete or ambiguous"
                    )
                else:
                    team_scores[:, ti] += row["points"]
                p = row.get("position")
                if (
                    kind == "R"
                    and row.get("classified")
                    and p
                    and 1 <= p <= len(drivers)
                ):
                    counts[:, i, int(p) - 1] += 1
                    if ti is not None:
                        team_counts[:, ti, int(p) - 1] += 1
    if include_weekend:
        earned = _points(draws, snapshot.get("_sprint", False))
        scores[:, : len(drivers)] += earned
        race = draws["R"]
        for i, driver in enumerate(drivers):
            ti = teams.index(str(driver["team_id"]))
            team_scores[:, ti] += earned[:, i]
            for p in range(1, len(drivers) + 1):
                finish = (race["ranks"][:, i] == p) & race["classified"][:, i]
                counts[:, i, p - 1] += finish
                team_counts[:, ti, p - 1] += finish
    return {
        "scores": scores,
        "counts": counts,
        "teams": teams,
        "team_scores": team_scores,
        "team_counts": team_counts,
        "team_error": error,
    }, None


def _race_events(question, snapshot, simulations, seed):
    from .predict_model import _bin, _text, _utc, _now

    text = _text(question["text"])
    safety = "safety car" in text or "vsc" in text
    red = "red flag" in text
    first_lap = "all" in text and "complete the first lap" in text
    if not (safety or red or first_lap):
        return None
    cutoff = min(
        _utc(snapshot["first_session_utc"]),
        _now(),
    )
    rows = [
        r
        for r in predict_evidence.document().get("predict_races", [])
        if _utc(r["end"]) < cutoff
    ]
    early = re.search(r"first (\d+) laps", text)
    values, events = [], []
    for row in sorted(rows, key=lambda r: _utc(r["end"])):
        if first_lap:
            value = row.get("all_complete_first_lap")
        elif red:
            value = row.get("red_flags")
        else:
            laps = row.get("safety_laps")
            value = (
                None
                if laps is None or (early and None in laps)
                else sum(
                    lap is None or not early or lap <= int(early[1]) for lap in laps
                )
            )
        if value is not None:
            values.append(int(value))
            events.append({k: row[k] for k in ("season", "round", "end")})
    if not values:
        return {
            "unsupported": "Completed pre-cutoff race-control/first-lap observations unavailable; refresh Predict history"
        }
    binary = first_lap or not (
        "how many" in text or "how many times" in text or "number" in text
    )
    samples = np.array(values)
    if binary:
        samples = samples > 0
        categories = np.arange(2)
    else:
        upper = max(
            (
                int(n)
                for o in question["options"]
                for n in re.findall(r"\d+", o["name"])
            ),
            default=0,
        )
        categories = np.arange(max(max(values), upper) + 2)
    # A recency-weighted categorical posterior. The symmetric half-observation
    # prior prevents an unobserved rare intervention from becoming impossible.
    weights = 2.0 ** (-np.arange(len(samples) - 1, -1, -1) / 20)
    mass = np.array([0.5 + weights[samples == c].sum() for c in categories])
    values = np.random.default_rng(seed).choice(
        categories, simulations, p=mass / mass.sum()
    )
    masks = (
        _yes_no(question["options"], values.astype(bool), _text)
        if binary
        else [_bin(o["name"], values) for o in question["options"]]
    )
    if any(m is None for m in masks):
        return {"unsupported": "Unrecognized race-control outcome bins"}
    return {
        "probabilities": {
            str(o["id"]): float(m.mean()) for o, m in zip(question["options"], masks)
        },
        "model_type": f"race-control-categorical-v1:{'first_lap' if first_lap else 'red_flags' if red else 'safety_car'}:{early[1] if early else 'all'}",
        "evidence": {
            "race_control_events": events,
            "prior_per_category": 0.5,
            "half_life_events": 20,
        },
    }


def question(question, snapshot, drivers, draws, records):
    from . import predict_model as model

    text, options = model._text(question["text"]), question["options"]
    count = len(next(iter(draws.values()))["ranks"])
    event = _race_events(question, snapshot, count, snapshot.get("_seed", 2026))
    if event is not None:
        return event
    masks, semantic, extra = None, None, {}
    team_ids = list(dict.fromkeys(str(d["team_id"]) for d in drivers))
    team_options = _teams(options, snapshot)
    tie_options = [model._text(o["name"]) in {"tie", "tied"} for o in options]
    sprint = "sprint" in text
    if ("q1" in text or "q2" in text or "q3" in text) and (
        "get" in text or "progress" in text
    ):
        kind = "SQ" if sprint else "Q"
        if kind not in draws or (sprint and not snapshot.get("_sprint")):
            return {"unsupported": "Separate Sprint qualifying evidence is required"}
        q = draws[kind]
        stage = int(re.search(r"q([123])", text)[1])
        if "out of q1" in text or "beyond q1" in text:
            stage = 2
        threshold = (
            10
            if stage == 3
            else (len(drivers) + 10) // 2
            if stage == 2
            else len(drivers)
        )
        reached = (q["ranks"] <= threshold) & q["classified"]
        if "how many teams" in text:
            number = sum(
                reached[:, _team_mask(drivers, team_id)].any(axis=1)
                for team_id in team_ids
            )
            masks = [model._bin(o["name"], number) for o in options]
            semantic = "teams_qstage_count"
        else:
            mentioned = model._mentioned_teams(text, snapshot["roster"])
            selected = [
                i for i, d in enumerate(drivers) if str(d["team_id"]) in mentioned
            ]
            if len(mentioned) != 1 or len(selected) != 2:
                return {
                    "unsupported": "Qualifying progression needs one verified two-car team"
                }
            value = (
                reached[:, selected].all(axis=1)
                if "both" in text
                else reached[:, selected].any(axis=1)
            )
            masks = _yes_no(options, value, model._text)
            semantic = "team_qstage_both" if "both" in text else "team_qstage_any"
    elif "how many teams" in text and "points" in text:
        if sprint and not snapshot.get("_sprint"):
            return {
                "unsupported": "Sprint question conflicts with verified weekend format"
            }
        kind = "S" if sprint else "R"
        scoring = (draws[kind]["ranks"] <= (8 if sprint else 10)) & draws[kind][
            "classified"
        ]
        number = sum(
            scoring[:, _team_mask(drivers, team_id)].any(axis=1) for team_id in team_ids
        )
        masks = [model._bin(o["name"], number) for o in options]
        semantic = f"{'sprint' if sprint else 'race'}_points_teams"
    elif "british" in text and ("points" in text or "win" in text):
        facts = predict_evidence.document().get("predict_facts", {})
        nationals = []
        for driver in drivers:
            matches = [
                r
                for r in facts.get("drivers", [])
                if r["tla"] == driver["tla"]
                and model._text(r["name"]).split()[-1]
                == model._text(driver["name"]).split()[-1]
            ]
            if len(matches) != 1 or not facts.get("source"):
                return {
                    "unsupported": "Sporting nationality must be sourced for every roster driver"
                }
            nationals.append(model._text(matches[0]["nationality"]) == "british")
        race = draws["S" if sprint else "R"]
        if "points" in text:
            number = (
                (race["ranks"][:, nationals] <= (8 if sprint else 10))
                & race["classified"][:, nationals]
            ).sum(axis=1)
            masks = [model._bin(o["name"], number) for o in options]
            semantic = "nationality_points_count"
        else:
            value = (
                (race["ranks"][:, nationals] == 1) & race["classified"][:, nationals]
            ).any(axis=1)
            masks = _yes_no(options, value, model._text)
            semantic = "nationality_winner"
        extra = {
            "sporting_nationality_source": facts["source"],
            "session": "S" if sprint else "R",
            "driver_tlas": [d["tla"] for d, yes in zip(drivers, nationals) if yes],
        }
    elif "new" in text and "grand prix winner" in text:
        match = re.search(r"new (.+ grand prix) winner", text)
        facts = predict_evidence.document().get("predict_facts", {})
        cutoff = min(model._utc(snapshot["first_session_utc"]), model._now())
        past = [
            r
            for r in facts.get("winners", [])
            if match
            and model._text(r["meeting"]) == match[1]
            and model._utc(r["end"]) < cutoff
        ]
        if (
            not facts.get("source")
            or not facts.get("winner_history_complete")
            or not past
        ):
            return {
                "unsupported": "New venue winner requires complete sourced Grand Prix winner history"
            }
        previous = {model._text(r["driver_name"]) for r in past}
        # Modern drivers have stable TLA plus surname identities; older winners
        # without a TLA are matched by their full source name only.
        eligible = [
            i
            for i, d in enumerate(drivers)
            if model._text(d["name"]) not in previous
            and not any(
                r.get("tla") == d["tla"]
                and model._text(r["driver_name"]).split()[-1]
                == model._text(d["name"]).split()[-1]
                for r in past
            )
        ]
        race = draws["R"]
        value = (
            (race["ranks"][:, eligible] == 1) & race["classified"][:, eligible]
        ).any(axis=1)
        masks = _yes_no(options, value, model._text)
        semantic = "new_venue_winner"
        extra = {
            "winner_history_source": facts["source"],
            "prior_winners": sorted(previous),
            "winner_history_cutoff": cutoff.isoformat(),
        }
    elif "most positions gained" in text:
        grid = snapshot.get("starting_grid")
        starting = (
            np.array([grid[d["tla"]] for d in drivers]) if grid else draws["Q"]["ranks"]
        )
        race = draws["R"]
        gain = np.where(race["classified"], starting - race["ranks"], 0).max(axis=1)
        masks = [model._bin(o["name"], np.maximum(0, gain)) for o in options]
        semantic = "maximum_positions_gained"
        extra = {
            "grid_model": "verified starting grid"
            if grid
            else "shared simulated qualifying; grid penalties not projected"
        }
    elif "championship" in text or ("champion" in text and "crowned" in text):
        world, error = _standings(snapshot, drivers, draws, records)
        if error:
            return {"unsupported": error}
        constructor = all(t is not None for t in team_options)
        if constructor and world["team_error"]:
            return {"unsupported": world["team_error"]}
        scores = world["team_scores"] if constructor else world["scores"]
        counts = world["team_counts"] if constructor else world["counts"]
        indices = (
            [world["teams"].index(t) for t in team_options]
            if constructor
            else [model._driver(o, drivers) for o in options]
        )
        if "crowned" in text and "weekend" in text:
            cutoff = model._utc(snapshot["first_session_utc"])
            try:
                events = model._season_events(snapshot, cutoff)
            except (model.DataError, KeyError) as exc:
                return {
                    "unsupported": f"Title-clinching needs a verified remaining schedule: {exc}"
                }
            target = [
                i
                for i, e in enumerate(events)
                if e["gameday_id"] == int(snapshot["gameday_id"])
            ]
            if len(target) != 1:
                return {
                    "unsupported": "Title-clinching target is absent from the verified schedule"
                }
            left = events[target[0] + 1 :]
            before, error = _standings(snapshot, drivers, draws, records, False)
            if error:
                return {"unsupported": error}
            value = model._clinched(
                scores, counts, len(left), sum(e["sprint"] for e in left)
            ) & ~model._clinched(
                before["scores"],
                before["counts"],
                len(left) + 1,
                sum(e["sprint"] for e in left) + int(snapshot.get("_sprint", False)),
            )
            masks = _yes_no(options, value, model._text)
            semantic = "title_clinched_this_weekend"
        elif all(i is not None for i in indices):
            if "ahead" in text and len(indices) == 2:
                ranks, resolved = model._rank_table(
                    scores[:, indices], counts[:, indices]
                )
                masks = [(ranks[:, j] == 1) & resolved[:, j] for j in range(2)]
            else:
                ranks, resolved = model._rank_table(scores, counts)
                position = 2 if "second" in text or "2nd" in text else 1
                masks = [(ranks[:, i] == position) & resolved[:, i] for i in indices]
            semantic = (
                "constructor_championship_h2h"
                if constructor
                else "champsecond"
                if ("second" in text or "2nd" in text)
                else "championship_leader"
            )
    elif (
        len([t for t in team_options if t is not None]) >= 2
        and all(t is not None or tie for t, tie in zip(team_options, tie_options))
        and ("points" in text or "highest race finishing" in text)
    ):
        race = draws["R"]
        compared = [t for t in team_options if t is not None]
        if "points" in text:
            earned = _points(draws, snapshot.get("_sprint", False))
            values = np.column_stack(
                [earned[:, _team_mask(drivers, t)].sum(axis=1) for t in compared]
            )
            semantic = "weekend_team_points"
        else:
            values = np.column_stack(
                [
                    -np.where(
                        race["classified"][:, _team_mask(drivers, t)],
                        race["ranks"][:, _team_mask(drivers, t)],
                        len(drivers) + 1,
                    ).min(axis=1)
                    for t in compared
                ]
            )
            semantic = "team_best_finish"
        best = values == values.max(axis=1)[:, None]
        unique = best.sum(axis=1) == 1
        masks = [
            ~unique if tie else best[:, compared.index(t)] & unique
            for t, tie in zip(team_options, tie_options)
        ]
        extra = {
            "tie_policy": "Explicit tied answer"
            if any(tie_options)
            else "No points for tied teams",
            "tie_probability": float((~unique).mean()),
        }
    if semantic is None:
        return None
    if masks is None or any(m is None for m in masks):
        return {
            "unsupported": "Unrecognized or ambiguous outcome contract: "
            + question["text"]
        }
    if (np.array(masks, dtype=int).sum(axis=0) > 1).any():
        return {"unsupported": "Question outcome bins overlap"}
    return {
        "probabilities": {
            str(o["id"]): float(m.mean()) for o, m in zip(options, masks)
        },
        "model_type": f"timing-team-regime-selector-v2:{'q' if 'qstage' in semantic else 'r'}:{semantic}",
        "evidence": extra,
    }
