"""Independent, pre-cutoff racing probabilities for official Predict questions.

Prices, payouts, public Chance hints and published answers are never features.
The simulation is a deliberately small, prior-smoothed racing model; its raw
probabilities are not a claim of calibration. Unknown predicates fail closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import unicodedata

import fastf1
import numpy as np

from .data import Asset, DataError, Weekend
from .history import configure_cache
from .telemetry_model import adjustments


def _utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise DataError("Predict model cutoff/history requires a timezone")
    return result.astimezone(timezone.utc)


def _now():
    return datetime.now(timezone.utc)


def _fastf1_utc(value):
    """FastF1 utc=True and LapStartDate are documented naive UTC values."""
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _text(value):
    value = "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[^a-z0-9<>+–-]+", " ", value.lower()).split())


def _number(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _history(season, cutoff):
    """Load completed events, including all current-season championship points.

    A six-hour completion margin on scheduled Race start is conservative. The
    result end is checked again after loading, guarding delayed sessions.
    """
    cutoff = min(cutoff, _now())
    from . import public_history as archive

    source = archive.current()
    if source and not source["update"]:
        events = [
            (
                archive.date(r["race_start"]) + timedelta(hours=6),
                int(key.split("/")[0]),
                r["RoundNumber"],
            )
            for key, r in source["document"]["events"].items()
            if int(key.split("/")[0]) in (season - 1, season)
        ]
        eligible = sorted(row for row in events if row[0] < cutoff)
        selected = [row for row in eligible if row[1] < season][-8:] + [
            row for row in eligible if row[1] == season
        ]
        records = [
            archive.racing_record(year, number, cutoff) for _, year, number in selected
        ]
        if not records or any(row is None for row in records):
            raise DataError("Public racing history is incomplete; refresh the dataset")
        return records
    configure_cache()
    candidates = []
    for year in (season - 1, season):
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        for _, event in schedule.iterrows():
            round_ = int(event["RoundNumber"])
            if round_ < 1:
                continue
            race_date = event.get_session_date("Race", utc=True)
            end = _fastf1_utc(race_date) + timedelta(hours=6)
            if end < cutoff:
                candidates.append((end, year, round_, event))
    candidates.sort(key=lambda item: item[0])
    # Previous-season form is bounded, but current-season standings need every GP.
    prior = [item for item in candidates if item[1] < season][-8:]
    selected = prior + [item for item in candidates if item[1] == season]
    records = []
    for end, year, round_, event in selected:
        cached = archive.racing_record(year, round_, cutoff)
        if cached is not None:
            records.append(cached)
            continue
        record = {
            "season": year,
            "round": round_,
            "end": end.isoformat(),
            "race_start_utc": _fastf1_utc(
                event.get_session_date("Race", utc=True)
            ).isoformat(),
            "sessions": {},
        }
        kinds = ["Q", "R"]
        event_format = str(event["EventFormat"]).lower()
        if "sprint" in event_format:
            kinds += ["S"]
        # FastF1 aliases SQ to the Sprint race for 2021/22. Only the distinct
        # 2023+ formats establish a separate Sprint qualifying session.
        if year >= 2023 and event_format in {"sprint_shootout", "sprint_qualifying"}:
            kinds += ["SQ"]
        for kind in kinds:
            identifier = (
                "SS" if kind == "SQ" and event_format == "sprint_shootout" else kind
            )
            session = fastf1.get_session(year, round_, identifier)
            session.load(
                laps=kind in {"R", "S"}, telemetry=False, weather=False, messages=False
            )
            results = session.results
            if results is None or results.empty:
                raise DataError(f"Missing Predict history: {year}/{round_}/{kind}")
            # Scheduled completion alone is insufficient if a loaded race ran late.
            if (
                kind in {"R", "S"}
                and session.laps is not None
                and not session.laps.empty
            ):
                times = session.laps.get("LapStartDate")
                if times is not None and times.notna().any():
                    actual_end = _fastf1_utc(times.dropna().max()) + timedelta(hours=1)
                    if actual_end >= cutoff:
                        raise DataError(
                            "Historical race/Sprint overlaps prediction cutoff"
                        )
                    record["end"] = max(_utc(record["end"]), actual_end).isoformat()
                laps = session.laps
                valid = laps["LapTime"].notna()
                if "Deleted" in laps:
                    valid &= ~laps["Deleted"].fillna(False).astype(bool)
                if valid.any():
                    record["fastest_lap" if kind == "R" else "sprint_fastest_lap"] = (
                        str(laps.loc[laps.loc[valid, "LapTime"].idxmin(), "Driver"])
                    )
            record["sessions"][kind] = [
                {
                    "tla": str(row["Abbreviation"]),
                    "position": _number(row.get("Position")),
                    "classified": _number(row.get("ClassifiedPosition")) is not None,
                    "points": _number(row.get("Points")),
                    "team_name": str(row.get("TeamName", "")),
                    "qualified": _number(row.get("Position")) is not None
                    and str(row.get("Status", "")).lower()
                    not in {"disqualified", "did not qualify", "did not start"},
                }
                for _, row in results.iterrows()
            ]
        records.append(record)
        archive.save_racing(record)
    return records


def _target(snapshot, cutoff):
    fixtures = snapshot["fixtures"]
    names = {str(f.get("MeetingName", "")) for f in fixtures if f.get("MeetingName")}
    if len(names) != 1:
        raise DataError("Predict target needs one unambiguous official meeting")
    from .public_history import event as get_event

    event = get_event(int(snapshot["season"]), names.pop())
    fixture_dates = [
        _utc(f["SessionStartDateISO8601"])
        for f in fixtures
        if f.get("SessionStartDateISO8601")
    ]
    if not fixture_dates or not (
        min(fixture_dates)
        <= _fastf1_utc(event.get_session_date("Race", utc=True))
        <= max(fixture_dates) + timedelta(hours=3)
    ):
        raise DataError(
            "FastF1 target race date disagrees with official Predict fixtures"
        )
    return Weekend(
        int(snapshot["season"]),
        int(event["RoundNumber"]),
        str(event["EventName"]),
        int(snapshot["gameday_id"]),
        cutoff,
        "sprint" in str(event["EventFormat"]).lower(),
        False,
    )


def _draw(records, drivers, simulations, rng, telemetry):
    n = len(drivers)
    tlas = [d["tla"] for d in drivers]
    form = records[-8:]
    forms = {
        kind: [r for r in records if r["sessions"].get(kind)][-8:]
        for kind in ("Q", "R", "S", "SQ")
    }
    kinds = ["Q", "R", "S"] + (["SQ"] if forms["SQ"] else [])
    means, retirement = {}, {}
    for kind in kinds:
        qualifying = kind in {"Q", "SQ"}
        means[kind], retirement[kind] = [], []
        for driver in drivers:
            observations = []
            failures = 0
            for index, record in enumerate(forms[kind]):
                rows = record["sessions"].get(kind, [])
                row = next((r for r in rows if r["tla"] == driver["tla"]), None)
                if row is not None:
                    failures += (
                        not row["classified"]
                        if not qualifying
                        else not row.get("qualified", True)
                    )
                    if row.get("position") and (qualifying or row["classified"]):
                        # Rescale differing grid sizes (e.g. 20 versus 22 entrants).
                        observations.append(
                            (index + 1, (row["position"] - 0.5) / len(rows) * n + 0.5)
                        )
            # A teammate-informed prior gives new entrants car information.
            teammate = [
                r["position"]
                for record in forms[kind]
                for r in record["sessions"].get(kind, [])
                if r.get("position")
                and any(
                    d["tla"] == r["tla"] and d["team_id"] == driver["team_id"]
                    for d in drivers
                )
            ]
            prior = float(np.mean(teammate)) if teammate else (n + 1) / 2
            mean = (3 * prior + sum(w * p for w, p in observations)) / (
                3 + sum(w for w, _ in observations)
            )
            delta = telemetry.get((0, str(driver["id"])), (0, 0, 0))[
                ("Q", "S", "R").index("Q" if kind == "SQ" else kind)
            ]
            means[kind].append(mean - max(-2.0, min(2.0, delta / 4)))
            count = sum(
                any(r["tla"] == driver["tla"] for r in record["sessions"].get(kind, []))
                for record in forms[kind]
            )
            retirement[kind].append(
                (failures + (0.15 if qualifying else 1.2)) / (count + 10)
            )
    # Bootstrap one complete historical weekend per draw, shared by sessions.
    # This retains observed field-wide rank/circuit variation rather than
    # independently treating each driver's previous race as a separate event.
    sampled_events = rng.integers(0, len(form), simulations)
    shared = rng.normal(0, 1.6, (simulations, n))
    output = {}
    for kind in kinds:
        empirical = np.array(
            [
                [
                    next(
                        (
                            (r["position"] - 0.5) / len(record["sessions"][kind]) * n
                            + 0.5
                            for r in record["sessions"].get(kind, [])
                            if r["tla"] == d["tla"] and r.get("position")
                        ),
                        means[kind][i],
                    )
                    for i, d in enumerate(drivers)
                ]
                for record in form
            ]
        )
        bootstrap = empirical[sampled_events] - empirical.mean(axis=0)
        performance = (
            np.array(means[kind])
            + 0.5 * bootstrap
            + shared
            + rng.normal(0, 2.8 if kind in {"Q", "SQ"} else 3.5, (simulations, n))
        )
        classified = rng.random((simulations, n)) >= np.array(retirement[kind])
        performance += (~classified) * (n * 3 + rng.random((simulations, n)) * n)
        order = np.argsort(performance, axis=1, kind="stable")
        ranks = np.empty_like(order)
        np.put_along_axis(ranks, order, np.arange(1, n + 1)[None, :], axis=1)
        output[kind] = {"ranks": ranks, "classified": classified}
    for kind, key in (("R", "fastest_lap"), ("S", "sprint_fastest_lap")):
        lap_history = [r for r in records if r.get(key)][-8:]
        if kind == "S" and not lap_history:
            continue
        counts = np.array([sum(r.get(key) == tla for r in lap_history) for tla in tlas])
        weights = (counts[None, :] + 2 / np.maximum(output[kind]["ranks"], 1)) * output[
            kind
        ]["classified"]
        # Even an all-retired draw has a fastest lap established before retirement.
        empty = weights.sum(axis=1) == 0
        weights[empty] = 1
        cumulative = np.cumsum(weights / weights.sum(axis=1)[:, None], axis=1)
        output[key] = (cumulative < rng.random((simulations, 1))).sum(axis=1)
    return output


def _driver(option, drivers):
    matches = [
        i
        for i, d in enumerate(drivers)
        if (str(option["id"]) == str(d["id"]) and int(option.get("kind", 1)) == 1)
        or (option.get("tla") and option["tla"] == d["tla"])
        or _text(option.get("name", "")) == _text(d["name"])
    ]
    return matches[0] if len(matches) == 1 else None


def _mentioned(text, drivers):
    matches = []
    for i, driver in enumerate(drivers):
        full = _text(driver["name"])
        last = full.split()[-1]
        if re.search(r"\b" + re.escape(full) + r"\b", text) or re.search(
            r"\b" + re.escape(last) + r"\b", text
        ):
            matches.append(i)
    return matches


def _mentioned_teams(text, roster):
    team_ids = set()
    for row in roster:
        name = row["name"] if int(row["kind"]) == 2 else row.get("team_name", "")
        name = _text(name)
        # Official names sometimes include the generic suffix "F1 Team".
        core = " ".join(
            word for word in name.split() if word not in {"f1", "formula", "1", "team"}
        )
        if any(
            alias and re.search(r"\b" + re.escape(alias) + r"\b", text)
            for alias in {name, core}
        ):
            team_ids.add(str(row["team_id"]))
    return team_ids


def _bin(label, values, classified=None):
    label = _text(label)
    label = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", label)
    if label in {"nc", "dnf", "not classified", "unclassified", "non classified"}:
        return ~classified if classified is not None else None
    if label in {"podium", "top 3", "top three"}:
        return (values <= 3) & classified if classified is not None else values <= 3
    match = re.fullmatch(r"([<>])\s*(\d+)", label)
    if match:
        result = values < int(match[2]) if match[1] == "<" else values > int(match[2])
    elif re.fullmatch(r"\d+", label):
        result = values == int(label)
    else:
        match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", label)
        if not match:
            return None
        result = (values >= int(match[1])) & (values <= int(match[2]))
    return result & classified if classified is not None else result


def _question(question, snapshot, drivers, draws, records):
    text = _text(question["text"])
    options = question["options"]
    template = int(question["template"])
    if template not in {1, 2, 3, 4, 6, 7, 8}:
        return {"unsupported": f"Unrecognized question template {template}"}
    if snapshot["scope"] != "round":
        return {
            "unsupported": "Season bonus predicates require a season-horizon model; round probabilities cannot answer them"
        }
    if "pitstop" in text or "pit stop" in text:
        return {
            "unsupported": "Stationary pitstop durations/DHL award history unavailable; pit-lane transit is not stationary-stop timing"
        }
    sprint = "sprint" in text or "shootout" in text
    qualifying = "quali" in text or "pole" in text or "shootout" in text
    fastest_lap = (
        "fastest lap" in text or "fastest sprint lap" in text
    ) and not qualifying
    kind = ("SQ" if qualifying else "S") if sprint else ("Q" if qualifying else "R")
    if sprint and not snapshot.get("_sprint"):
        return {
            "unsupported": "Sprint question conflicts with verified regular-weekend format"
        }
    if kind == "SQ" and "SQ" not in draws:
        return {
            "unsupported": "Sprint qualifying requires separate session evidence; no completed pre-cutoff SQ/SS history"
        }
    lap_key = "sprint_fastest_lap" if kind == "S" else "fastest_lap"
    if fastest_lap and lap_key not in draws:
        return {
            "unsupported": "Sprint fastest lap requires timed laps from completed pre-cutoff Sprint sessions"
        }
    ranks, classified = draws[kind]["ranks"], draws[kind]["classified"]
    indices = [_driver(option, drivers) for option in options]
    masks = None
    model = "joint-racing-rank-bootstrap-prior-v1"
    semantic = None
    extra = {}
    if template == 1 and "podium" in text and all(i is not None for i in indices):
        return {
            "position_probabilities": {
                str(option["id"]): [
                    float(np.mean((ranks[:, i] == p) & classified[:, i]))
                    for p in (1, 2, 3)
                ]
                for option, i in zip(options, indices)
            },
            "model_type": f"{model}:{kind.lower()}:podium",
        }
    if (
        template == 7
        and len(options) == 2
        and all(i is not None for i in indices)
        and (
            "head to head" in text
            or "h2h" in text
            or "finish" in text
            or "qualif" in text
            or "shootout" in text
        )
    ):
        semantic = "quali_h2h" if qualifying else "race_h2h"
        a, b = indices
        masks = [
            classified[:, a] & ((ranks[:, a] < ranks[:, b]) | ~classified[:, b]),
            classified[:, b] & ((ranks[:, b] < ranks[:, a]) | ~classified[:, a]),
        ]
    elif (fastest_lap or ("fastest" in text and qualifying) or "pole" in text) and all(
        i is not None for i in indices
    ):
        semantic = "fastest_lap" if fastest_lap else "pole"
        masks = [
            draws[lap_key] == i
            if fastest_lap
            else (ranks[:, i] == 1) & classified[:, i]
            for i in indices
        ]
    elif (
        ("highest" in text or "best" in text or ("finish" in text and "ahead" in text))
        and ("race" in text or "finish" in text)
        and all(i is not None for i in indices)
    ):
        semantic = "midfield"
        subset = np.argmin(
            np.where(classified[:, indices], ranks[:, indices], len(drivers) * 2),
            axis=1,
        )
        any_finished = classified[:, indices].any(axis=1)
        masks = [(subset == j) & any_finished for j in range(len(indices))]
    elif (
        "championship" in text
        and ("second" in text or "2nd" in text)
        and ("leave" in text or "after" in text)
        and all(i is not None for i in indices)
    ):
        semantic = "champsecond"
        # Full season-to-date official Points, including Sprints, never standings API.
        totals = np.zeros(len(drivers))
        for record in records:
            if record["season"] != int(snapshot["season"]):
                continue
            for session in ("R", "S"):
                for row in record["sessions"].get(session, []):
                    if row.get("points") is None:
                        return {
                            "unsupported": "Official historical championship points incomplete"
                        }
                    for i, d in enumerate(drivers):
                        if row["tla"] == d["tla"]:
                            totals[i] += row["points"]
        points = np.array([0, 25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * len(drivers))
        scores = totals + points[draws["R"]["ranks"]] * draws["R"]["classified"]
        if snapshot.get("_sprint"):
            scores += np.maximum(0, 9 - draws["S"]["ranks"]) * draws["S"]["classified"]
        # FIA countback from recorded and simulated finishing classifications.
        keys = []
        for i, d in enumerate(drivers):
            counts = [
                sum(
                    r["tla"] == d["tla"] and r.get("position") == p
                    for rec in records
                    if rec["season"] == int(snapshot["season"])
                    for r in rec["sessions"].get("R", [])
                )
                + (draws["R"]["ranks"][:, i] == p)
                for p in range(len(drivers), 0, -1)
            ]
            keys.append(counts)
        countback = np.stack([np.stack(k) for k in keys], axis=1).transpose(0, 2, 1)
        order = np.lexsort(tuple(countback) + (scores,), axis=1)[:, ::-1]
        masks = [order[:, 1] == i for i in indices]
    elif (
        "classif" in text
        and ("how many" in text or "number" in text or "count" in text)
        and ("finish" in text or "driver" in text)
    ):
        team_ids = _mentioned_teams(text, snapshot["roster"])
        selected = (
            [i for i, d in enumerate(drivers) if str(d["team_id"]) in team_ids]
            if team_ids
            else list(range(len(drivers)))
        )
        if team_ids - {str(drivers[i]["team_id"]) for i in selected}:
            return {
                "unsupported": "Named constructor has no verified drivers for classified count"
            }
        scope = "teams" if team_ids else "grid"
        semantic = f"classified_count:{scope}"
        extra = {
            "classified_count_scope": scope,
            "classified_driver_tlas": [drivers[i]["tla"] for i in selected],
        }
        masks = [_bin(o["name"], classified[:, selected].sum(axis=1)) for o in options]
    elif (
        "furthest" in text or "farthest" in text or "how far" in text or "stage" in text
    ) and qualifying:
        semantic = "team_qstage"
        team_ids = _mentioned_teams(text, snapshot["roster"])
        team = [i for i, d in enumerate(drivers) if str(d["team_id"]) in team_ids]
        if len(team_ids) == 1 and team:
            best = ranks[:, team].min(axis=1)
            # Q3 has ten cars, Q2 eliminates six on a 22-car grid (five on 20).
            stage = np.where(
                best <= 10, 3, np.where(best <= (len(drivers) + 10) // 2, 2, 1)
            )
            masks = [
                stage == int(o["name"][-1])
                if re.fullmatch(r"(?:SQ|Q)[123]", o["name"], re.I)
                else None
                for o in options
            ]
    elif "finish" in text and ("where" in text or "position" in text):
        semantic = "finish_bin"
        mentioned = _mentioned(text, drivers)
        if len(mentioned) == 1:
            i = mentioned[0]
            masks = [_bin(o["name"], ranks[:, i], classified[:, i]) for o in options]
    if masks is None or any(mask is None for mask in masks):
        return {
            "unsupported": "Unrecognized or ambiguous question predicate/options: "
            + question["text"]
        }
    if (
        sum(int(m.sum()) for m in masks) > len(ranks)
        and int(question.get("choice_limit", 1)) == 1
    ):
        return {"unsupported": "Question outcome bins overlap"}
    return {
        "probabilities": {
            str(o["id"]): float(np.mean(m)) for o, m in zip(options, masks)
        },
        "model_type": f"{model}:{kind.lower()}:{semantic}",
        "evidence": extra,
    }


def _season_events(snapshot, cutoff):
    """Group the supplied official schedule, never fetch future session results."""
    fixtures = snapshot.get("season_fixtures")
    if not fixtures:
        raise DataError(
            "Predict season-horizon requires the complete official season_fixtures"
        )
    groups = {}
    for row in fixtures:
        if int(row["Season"]) != int(snapshot["season"]) or int(
            row.get("IsBonusRound", 0)
        ):
            raise DataError("Season-horizon fixtures have contradictory season/scope")
        groups.setdefault(int(row["GamedayId"]), []).append(row)
    events = []
    for gameday, rows in groups.items():
        races = [r for r in rows if _text(r["SessionType"]) in {"race", "grand prix"}]
        if len(races) != 1 or any(int(r.get("IsPostponed", 0)) for r in rows):
            raise DataError(
                "Season-horizon needs one scheduled Race per distinct gameday"
            )
        starts = [_utc(r["SessionStartDateISO8601"]) for r in rows]
        end = max(_utc(r["SessionEndDateISO8601"]) for r in rows)
        if min(starts) < cutoff <= end:
            raise DataError(
                "Season-horizon cutoff overlaps a weekend; partial session results are not inputs"
            )
        events.append(
            {
                "gameday_id": gameday,
                "name": str(races[0]["MeetingName"]),
                "race_start": _utc(races[0]["SessionStartDateISO8601"]),
                "first_session": min(starts),
                "completed": end < cutoff,
                "sprint": any("sprint" in _text(r["SessionType"]) for r in rows),
            }
        )
    return sorted(events, key=lambda e: e["race_start"])


def _rank_table(scores, counts):
    """FIA race-result countback; exact unresolved ties retain no arbitrary winner."""
    order = np.lexsort(
        tuple(counts[:, :, ::-1].transpose(2, 0, 1)) + (scores,), axis=1
    )[:, ::-1]
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(1, scores.shape[1] + 1)[None, :], axis=1)
    ordered_scores = np.take_along_axis(scores, order, axis=1)
    ordered_counts = np.take_along_axis(counts, order[:, :, None], axis=1)
    tied = (ordered_scores[:, :-1] == ordered_scores[:, 1:]) & np.all(
        ordered_counts[:, :-1] == ordered_counts[:, 1:], axis=2
    )
    resolved_order = np.ones_like(order, dtype=bool)
    resolved_order[:, :-1] &= ~tied
    resolved_order[:, 1:] &= ~tied
    resolved = np.empty_like(resolved_order)
    np.put_along_axis(resolved, order, resolved_order, axis=1)
    return ranks, resolved


def _clinched(scores, counts, races_left, sprints_left):
    """Prove a title cannot be lost, including countback at equal maximum points."""
    leader = _rank_table(scores, counts)[0].argmin(axis=1)
    at = np.arange(len(scores))
    gap = scores[at, leader, None] - scores
    best_counts = counts.copy()
    # To recover the full remaining 25/8 maximum, a challenger must win every GP.
    best_counts[:, :, 0] += races_left
    difference = counts[at, leader, None, :] - best_counts
    first = (difference != 0).argmax(axis=2)
    countback_wins = (
        np.take_along_axis(difference, first[:, :, None], axis=2)[:, :, 0] > 0
    )
    maximum = 25 * races_left + 8 * sprints_left
    beaten = (gap > maximum) | ((gap == maximum) & countback_wins)
    beaten[at, leader] = True
    return beaten.all(axis=1)


def _season_world(snapshot, drivers, records, events, simulations, rng):
    n = len(drivers)
    tlas = {d["tla"]: i for i, d in enumerate(drivers)}
    teams = list(dict.fromkeys(str(d["team_id"]) for d in drivers))
    team_indices = np.array([teams.index(str(d["team_id"])) for d in drivers])
    team_names = {}
    for row in snapshot["roster"]:
        name = row["name"] if int(row["kind"]) == 2 else row.get("team_name", "")
        if name:
            team_names.setdefault(_text(name), set()).add(str(row["team_id"]))
    scores = np.zeros((simulations, n))
    counts = np.zeros((simulations, n, n), dtype=int)
    team_scores = np.zeros((simulations, len(teams)))
    team_counts = np.zeros((simulations, len(teams), n), dtype=int)
    poles = np.zeros_like(scores, dtype=int)
    laps = np.zeros_like(scores, dtype=int)
    wins = np.zeros_like(scores, dtype=int)
    h2h = np.zeros((simulations, n, n), dtype=np.int16)
    errors = {}
    historical = [r for r in records if int(r["season"]) == int(snapshot["season"])]
    completed = [e for e in events if e["completed"]]
    if len(completed) != len(historical):
        raise DataError(
            "Season-horizon completed schedule/history coverage is incomplete"
        )
    mapping = {}
    for event in completed:
        matches = [
            r
            for r in historical
            if r.get("race_start_utc")
            and abs((_utc(r["race_start_utc"]) - event["race_start"]).total_seconds())
            <= 3 * 3600
        ]
        if len(matches) != 1 or id(matches[0]) in mapping.values():
            raise DataError(
                "Season-horizon cannot uniquely bind completed history to official fixtures"
            )
        mapping[event["gameday_id"]] = id(matches[0])
    decided = np.full(simulations, -1, dtype=int)
    historical_winners = set()
    points = np.array([0, 25, 18, 15, 12, 10, 8, 6, 4, 2, 1] + [0] * n)
    at = np.arange(simulations)
    for index, event in enumerate(events):
        if event["completed"]:
            record = next(
                r for r in historical if id(r) == mapping[event["gameday_id"]]
            )
            q = {
                "ranks": np.full((simulations, n), n + 1),
                "classified": np.zeros((simulations, n), dtype=bool),
            }
            for row in record["sessions"].get("Q", []):
                if row["tla"] in tlas:
                    i = tlas[row["tla"]]
                    q["ranks"][:, i] = row.get("position") or n + 1
                    q["classified"][:, i] = row.get("qualified", False)
            if not record["sessions"].get("Q"):
                errors["qualifying"] = "Completed qualifying history is incomplete"
            if any(r["tla"] not in tlas for r in record["sessions"].get("Q", [])):
                errors["qualifying"] = (
                    "Completed qualifying includes competitors outside the verified roster"
                )
            race_winners = [
                r
                for r in record["sessions"].get("R", [])
                if r.get("position") == 1 and r.get("classified")
            ]
            if len(race_winners) != 1:
                errors["winners"] = "Completed Grand Prix winner history is incomplete"
            if not record.get("fastest_lap") or record["fastest_lap"] not in tlas:
                errors["fastest_lap"] = (
                    "Completed season fastest-lap history is incomplete or outside the verified roster"
                )
            else:
                laps[:, tlas[record["fastest_lap"]]] += 1
            for kind in ("R", "S") if event["sprint"] else ("R",):
                rows = record["sessions"].get(kind, [])
                if not rows:
                    errors["standings"] = (
                        "Official historical championship points are incomplete"
                    )
                for row in rows:
                    i = tlas.get(row["tla"])
                    if row.get("points") is None or (i is None and row["points"] != 0):
                        errors["standings"] = (
                            "Official historical points are incomplete or include unmapped competitors"
                        )
                    if i is not None and row.get("points") is not None:
                        scores[:, i] += row["points"]
                    team = team_names.get(_text(row.get("team_name", "")), set())
                    team_i = (
                        teams.index(next(iter(team)))
                        if len(team) == 1 and next(iter(team)) in teams
                        else None
                    )
                    if team_i is None:
                        errors["constructors"] = (
                            "Historical constructor attribution does not uniquely match verified roster teams"
                        )
                    elif row.get("points") is not None:
                        team_scores[:, team_i] += row["points"]
                    position = row.get("position")
                    if (
                        kind == "R"
                        and row.get("classified")
                        and position
                        and 1 <= position <= n
                    ):
                        if i is not None:
                            counts[:, i, int(position) - 1] += 1
                        if team_i is not None:
                            team_counts[:, team_i, int(position) - 1] += 1
                    if kind == "R" and position == 1 and row.get("classified"):
                        historical_winners.add(row["tla"])
        else:
            draw = _draw(records, drivers, simulations, rng, {})
            q = draw["Q"]
            for kind in ("R", "S") if event["sprint"] else ("R",):
                rank, classified = draw[kind]["ranks"], draw[kind]["classified"]
                earned = (
                    points[rank] if kind == "R" else np.maximum(0, 9 - rank)
                ) * classified
                scores += earned
                for team_i in range(len(teams)):
                    team_scores[:, team_i] += earned[:, team_indices == team_i].sum(
                        axis=1
                    )
                if kind == "R":
                    for p in range(1, n + 1):
                        finish = (rank == p) & classified
                        counts[:, :, p - 1] += finish
                        for team_i in range(len(teams)):
                            team_counts[:, team_i, p - 1] += finish[
                                :, team_indices == team_i
                            ].sum(axis=1)
                    wins += (rank == 1) & classified
            laps[at, draw["fastest_lap"]] += 1
        poles += (q["ranks"] == 1) & q["classified"]
        h2h += q["classified"][:, :, None] & (
            (q["ranks"][:, :, None] < q["ranks"][:, None, :])
            | ~q["classified"][:, None, :]
        )
        remaining = events[index + 1 :]
        proven = _clinched(
            scores, counts, len(remaining), sum(e["sprint"] for e in remaining)
        )
        decided[(decided < 0) & proven] = index
    return {
        "scores": scores,
        "counts": counts,
        "team_scores": team_scores,
        "team_counts": team_counts,
        "teams": teams,
        "poles": poles,
        "fastest_lap": laps,
        "wins": wins,
        "qualifying_wins": h2h,
        "historical_winners": historical_winners,
        "decided": decided,
        "errors": errors,
    }


def _prior_titles(snapshot, key, events, cutoff):
    """Caller-supplied complete, sourced pre-season facts; never infer a career from eight GPs."""
    facts = snapshot.get(key, {})
    try:
        if (
            facts["complete"] is not True
            or not facts["source"]
            or int(facts["season"]) != int(snapshot["season"])
            or _utc(facts["as_of_utc"]) >= min(cutoff, events[0]["first_session"])
        ):
            return None
        values = facts["driver_tlas"]
        if not isinstance(values, list) or any(
            not isinstance(tla, str) or not tla for tla in values
        ):
            return None
        return set(values)
    except (KeyError, TypeError, ValueError):
        return None


def _season_question(question, snapshot, drivers, events, world, cutoff):
    text, options = _text(question["text"]), question["options"]
    template = int(question["template"])
    if template not in {1, 2, 3, 4, 6, 7, 8}:
        return {"unsupported": f"Unrecognized question template {template}"}
    if "pitstop" in text or "pit stop" in text:
        return {
            "unsupported": "Stationary season-fastest pitstop timing is unavailable"
        }
    driver_indices = [_driver(o, drivers) for o in options]
    team_indices = []
    for option in options:
        matches = {
            str(r["team_id"])
            for r in snapshot["roster"]
            if int(option.get("kind", 0)) == 2
            and int(r["kind"]) == 2
            and (
                str(r["id"]) == str(option["id"])
                or _text(r["name"]) == _text(option["name"])
            )
        }
        team_indices.append(
            world["teams"].index(next(iter(matches)))
            if len(matches) == 1 and next(iter(matches)) in world["teams"]
            else None
        )
    masks, error_key = None, None
    extra = {}
    semantic = None
    championship = "championship" in text or "champion" in text
    if (
        ("first-time" in text or "first time" in text)
        and "grand prix" in text
        and "winner" in text
    ):
        error_key = "winners"
        semantic = "first_time_winners"
        prior = _prior_titles(snapshot, "prior_grand_prix_winners", events, cutoff)
        if prior is None:
            return {
                "unsupported": "First-time winners require a complete sourced pre-season prior_grand_prix_winners set"
            }
        extra["prior_grand_prix_winners"] = snapshot["prior_grand_prix_winners"]
        base = len(world["historical_winners"] - prior)
        eligible = [
            i
            for i, d in enumerate(drivers)
            if d["tla"] not in prior | world["historical_winners"]
        ]
        number = base + (world["wins"][:, eligible] > 0).sum(axis=1)
        masks = [_bin(o["name"], number) for o in options]
    elif championship and ("decided" in text or "clinch" in text):
        error_key = "standings"
        semantic = "championship_decided"
        if (world["decided"] < 0).any():
            return {
                "unsupported": "Championship location is unresolved by simulated points/countback",
                "evidence": {
                    "unresolved_probability": float(np.mean(world["decided"] < 0))
                },
            }
        locations = []
        for option in options:
            label = _text(option["name"])
            matches = [
                i
                for i, event in enumerate(events)
                if label != "earlier"
                and re.search(r"\b" + re.escape(label) + r"\b", _text(event["name"]))
            ]
            locations.append(matches[0] if len(matches) == 1 else None)
        named = [i for i in locations if i is not None]
        masks = [
            world["decided"] < min(named)
            if _text(o["name"]) == "earlier" and named
            else world["decided"] == i
            if i is not None
            else None
            for o, i in zip(options, locations)
        ]
    elif (
        "qualif" in text
        and template == 7
        and len(options) == 2
        and all(i is not None for i in driver_indices)
    ):
        error_key = "qualifying"
        semantic = "gp_quali_h2h"
        a, b = driver_indices
        masks = [
            world["qualifying_wins"][:, a, b] > world["qualifying_wins"][:, b, a],
            world["qualifying_wins"][:, b, a] > world["qualifying_wins"][:, a, b],
        ]
    elif ("most" in text and "pole" in text) or (
        "fastest lap" in text and ("award" in text or "most" in text)
    ):
        error_key = "qualifying" if "pole" in text else "fastest_lap"
        semantic = "most_gp_poles" if "pole" in text else "fastest_lap_award"
        if all(i is not None for i in driver_indices):
            values = world["poles"] if "pole" in text else world["fastest_lap"]
            leaders = values == values.max(axis=1)[:, None]
            unique = leaders.sum(axis=1) == 1
            if not unique.all():
                return {
                    "unsupported": "Season count award has tied leaders; settlement tiebreak is unestablished",
                    "evidence": {"unresolved_tie_probability": float(np.mean(~unique))},
                }
            masks = [leaders[:, i] for i in driver_indices]
    elif championship and "new" in text:
        error_key = "standings"
        semantic = "new_champion"
        prior = _prior_titles(snapshot, "prior_driver_champions", events, cutoff)
        if prior is None:
            return {
                "unsupported": "New champion requires a complete sourced pre-season prior_driver_champions set"
            }
        extra["prior_driver_champions"] = snapshot["prior_driver_champions"]
        ranks, resolved = _rank_table(world["scores"], world["counts"])
        champion = ranks.argmin(axis=1)
        if not resolved[np.arange(len(champion)), champion].all():
            return {
                "unsupported": "Championship winner remains tied after FIA countback"
            }
        new = np.array([drivers[i]["tla"] not in prior for i in champion])
        masks = [
            new
            if _text(o["name"]) == "yes"
            else ~new
            if _text(o["name"]) == "no"
            else None
            for o in options
        ]
    elif (championship or ("constructors" in text and "battle" in text)) and (
        all(i is not None for i in driver_indices)
        or all(i is not None for i in team_indices)
    ):
        constructor = all(i is not None for i in team_indices)
        error_key = "constructors" if constructor else "standings"
        indices = team_indices if constructor else driver_indices
        ranks, resolved = _rank_table(
            world["team_scores"] if constructor else world["scores"],
            world["team_counts"] if constructor else world["counts"],
        )
        if template == 1 and not constructor and ("top 3" in text or "podium" in text):
            if "standings" in world["errors"]:
                return {"unsupported": world["errors"]["standings"]}
            if (~resolved & (ranks <= 3)).any():
                return {
                    "unsupported": "Championship podium remains tied after FIA countback"
                }
            return {
                "position_probabilities": {
                    str(o["id"]): [float(np.mean(ranks[:, i] == p)) for p in (1, 2, 3)]
                    for o, i in zip(options, indices)
                },
                "model_type": "joint-season-racing-bootstrap-prior-v1:driver_championship_podium",
            }
        if template == 7 and len(indices) == 2:
            semantic = (
                "constructor_championship_h2h"
                if constructor
                else "driver_championship_h2h"
            )
            a, b = indices
            # A tie with a third entrant cannot affect this H2H; compare just the pair.
            pair, valid = _rank_table(
                (world["team_scores"] if constructor else world["scores"])[:, [a, b]],
                (world["team_counts"] if constructor else world["counts"])[:, [a, b]],
            )
            if not valid.all():
                return {"unsupported": "Season H2H remains tied after FIA countback"}
            masks = [pair[:, 0] == 1, pair[:, 1] == 1]
        elif "title" in text or "win" in text or "crowned champion" in text:
            semantic = (
                "constructor_championship_winner"
                if constructor
                else "driver_championship_winner"
            )
            if (~resolved & (ranks == 1)).any():
                return {
                    "unsupported": "Championship winner remains tied after FIA countback"
                }
            masks = [ranks[:, i] == 1 for i in indices]
    if error_key in world["errors"]:
        return {"unsupported": world["errors"][error_key]}
    if error_key == "constructors" and "standings" in world["errors"]:
        return {"unsupported": world["errors"]["standings"]}
    if masks is None or any(m is None for m in masks):
        return {
            "unsupported": "Unrecognized or ambiguous season predicate/options: "
            + question["text"]
        }
    if ("qualif" in text and template == 7) and not np.logical_or.reduce(masks).all():
        return {
            "unsupported": "Season qualifying H2H is tied; settlement tiebreak is unestablished",
            "evidence": {
                "unresolved_tie_probability": float(
                    np.mean(~np.logical_or.reduce(masks))
                )
            },
        }
    if (
        sum(int(m.sum()) for m in masks) > len(masks[0])
        and int(question.get("choice_limit", 1)) == 1
    ):
        return {"unsupported": "Season outcome bins overlap"}
    return {
        "probabilities": {
            str(o["id"]): float(np.mean(m)) for o, m in zip(options, masks)
        },
        "model_type": f"joint-season-racing-bootstrap-prior-v1:{semantic}",
        "evidence": extra,
    }


def _season_forecast(snapshot, drivers, cutoff, simulations, seed):
    evidence = {
        "cutoff_utc": cutoff.isoformat(),
        "target_first_session_utc": _utc(snapshot["first_session_utc"]).isoformat(),
        "scope": "season",
        "simulations": simulations,
        "seed": seed,
        "calibrated": False,
        "telemetry_adjustments": False,
    }
    try:
        events = _season_events(snapshot, cutoff)
        try:
            history = _history(int(snapshot["season"]), cutoff)
        except DataError:
            raise
        except Exception as exc:
            raise DataError(
                f"Cannot verify pre-cutoff Predict racing data: {exc}"
            ) from exc
        records = sorted(
            (r for r in history if _utc(r["end"]) < cutoff),
            key=lambda r: _utc(r["end"]),
        )
        if not records or not any(r["sessions"].get("R") for r in records):
            raise DataError("No completed pre-cutoff racing history")
        world = _season_world(
            snapshot, drivers, records, events, simulations, np.random.default_rng(seed)
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {
            int(q["id"]): {"unsupported": str(exc), "evidence": evidence}
            for q in snapshot["questions"]
        }
    evidence.update(
        {
            "historical_events": [
                {"season": r["season"], "round": r["round"], "end": r["end"]}
                for r in records
            ],
            "simulated_gamedays": [
                e["gameday_id"] for e in events if not e["completed"]
            ],
            "sprint_gamedays": [
                e["gameday_id"] for e in events if not e["completed"] and e["sprint"]
            ],
            "assumptions": [
                "One shared simulated season answers every question; completed points and counts are frozen at cutoff",
                "Future races use full-distance FIA 25-18-15-12-10-8-6-4-2-1; Sprint uses 8 through 1; no fastest-lap bonus",
                "Driver/team composition and pre-cutoff form are held fixed across the horizon",
                "Sprint-labelled official fixtures identify Sprint weekends; only Grand Prix qualifying counts toward poles/H2H",
                "Season simulation omits circuit-specific telemetry to preserve the single historical cutoff",
                "Count-award and qualifying-H2H ties require verified settlement rules; no arbitrary tie winner",
            ],
        }
    )
    output = {}
    for question in snapshot["questions"]:
        result = _season_question(question, snapshot, drivers, events, world, cutoff)
        result["evidence"] = {**evidence, **result.get("evidence", {})}
        output[int(question["id"])] = result
    return output


def forecast(snapshot, *, simulations=4000, seed=2026, use_telemetry=True):
    """Return supported question marginals; no payout-driven feature engineering.

    Season scope consumes the complete official ``season_fixtures``. Optional
    ``prior_grand_prix_winners`` and ``prior_driver_champions`` must each contain
    ``season``, ``driver_tlas``, ``complete=True``, ``source``, and an aware
    ``as_of_utc`` predating both cutoff and the first season fixture. They attest
    complete pre-season career facts, not merely this model's recent GP history.
    """
    if not isinstance(simulations, int) or simulations < 1:
        raise ValueError("simulations must be a positive integer")
    target_cutoff = _utc(snapshot["first_session_utc"])
    cutoff = min(target_cutoff, _now())
    drivers = [d for d in snapshot["roster"] if int(d["kind"]) == 1]
    if (
        len(drivers) < 3
        or len({d["tla"] for d in drivers}) != len(drivers)
        or any(not d["tla"] for d in drivers)
    ):
        raise DataError("Predict requires a verified, unique driver roster")
    if snapshot["scope"] == "season":
        return _season_forecast(snapshot, drivers, cutoff, simulations, seed)
    if snapshot["scope"] != "round":
        raise DataError("Unknown Predict forecast scope")
    try:
        history = _history(int(snapshot["season"]), cutoff)
        weekend = _target(snapshot, cutoff)
    except DataError:
        raise
    except Exception as exc:
        raise DataError(f"Cannot verify pre-cutoff Predict racing data: {exc}") from exc
    records = sorted(
        (r for r in history if _utc(r["end"]) < cutoff), key=lambda r: _utc(r["end"])
    )
    if not records or not any(r["sessions"].get("R") for r in records):
        raise DataError("No completed pre-cutoff racing history")
    telemetry = {}
    if use_telemetry:
        assets = tuple(
            Asset(str(d["id"]), d["name"], "DRIVER", d["team_id"], 0, d["tla"])
            for d in drivers
        )
        telemetry = adjustments(assets, [weekend])
    draws = _draw(records, drivers, simulations, np.random.default_rng(seed), telemetry)
    context = {**snapshot, "_sprint": weekend.sprint}
    evidence = {
        "cutoff_utc": cutoff.isoformat(),
        "target_first_session_utc": target_cutoff.isoformat(),
        "simulations": simulations,
        "seed": seed,
        "historical_events": [
            {"season": r["season"], "round": r["round"], "end": r["end"]}
            for r in records
        ],
        "form_lookback": min(8, len(records)),
        "telemetry_adjustments": bool(telemetry),
        "calibrated": False,
        "assumptions": [
            "Prior-smoothed recent racing ranks and classification rates with whole-weekend bootstrap",
            "Shared driver-performance noise couples Q, distinct SQ, Sprint and race, with separate session noise",
            "Race and Sprint fastest-lap histories are separate and blend with their own simulated session ranks",
            "Championship uses official prior-session points and FIA race-position countback",
        ],
    }
    output = {}
    for question in snapshot["questions"]:
        result = _question(question, context, drivers, draws, records)
        if "unsupported" not in result:
            result["evidence"] = {**evidence, **result.get("evidence", {})}
        output[int(question["id"])] = result
    return output
