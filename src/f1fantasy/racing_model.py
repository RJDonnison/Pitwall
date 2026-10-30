"""Margin-aware joint racing model and nested chronological model selection.

Timing is in percent of a lap, not positions. All fitting consumes completed
historical weekends only. The old model and simple baselines remain competitors;
new complexity is used only when its walk-forward score beats those baselines.
"""

from functools import lru_cache
from datetime import timedelta
import json
from itertools import product

import numpy as np

VERSION = "timing-team-regime-walkforward-v2"
PARAMETERS = [
    {
        "half_life": half,
        "temperature": temp,
        "team_share": share,
        "grid_weight": grid,
        "prior": 4.0,
    }
    for half, temp, share, grid in product(
        (2.0, 6.0), (0.4, 0.8), (0.35, 0.7), (0.0, 0.6)
    )
]


def roster(record):
    return [
        {
            "id": r["tla"],
            "tla": r["tla"],
            "name": r["tla"],
            "team_id": r.get("team_name", r["tla"]),
            "team_name": r.get("team_name", ""),
            "season": record["season"],
        }
        for r in record["sessions"]["R"]
    ]


def timed(records):
    recent = records[-8:]
    return len(recent) >= 4 and all(
        sum(r.get("pace_gap_pct") is not None for r in rec["sessions"].get(k, []))
        >= len(rec["sessions"].get(k, [])) / 2
        > 0
        for rec in recent
        for k in ("Q", "R")
    )


def _pace(row, kind):
    phases = row.get("qualifying_gaps_pct", {})
    if kind in {"Q", "SQ"} and phases:
        return min(phases.values())
    return row.get("pace_gap_pct")


def _form(records, drivers, kind, params):
    # Sprint and SQ borrow race/qualifying car pace, not a uniform rank prior.
    primary = [r for r in records if r["sessions"].get(kind)]
    source = primary if kind not in {"S", "SQ"} else records
    fallback = "R" if kind == "S" else "Q" if kind == "SQ" else kind
    driver_values = {d["tla"]: [] for d in drivers}
    team_values = {d["team_id"]: [] for d in drivers}
    latest_team = {
        row["tla"]: row.get("team_name")
        for rec in records
        for row in rec["sessions"].get("R", [])
    }
    teams = {
        d["team_id"]: d.get("team_name") or latest_team.get(d["tla"]) for d in drivers
    }
    target_season = max(d.get("season", records[-1]["season"]) for d in drivers)
    for index, rec in enumerate(source):
        weight = 2 ** (-(len(source) - index - 1) / params["half_life"])
        older = rec["season"] < target_season
        car_weight = 0.02 if older and target_season == 2026 else 0.25 if older else 1.0
        kinds = [(kind, 1.0)] if kind == fallback else [(kind, 1.0), (fallback, 0.5)]
        for session_kind, share in kinds:
            for row in rec["sessions"].get(session_kind, []):
                value = _pace(row, session_kind)
                if value is None or not np.isfinite(value):
                    continue
                peers = [
                    _pace(p, session_kind)
                    for p in rec["sessions"][session_kind]
                    if p.get("team_name") == row.get("team_name")
                    and _pace(p, session_kind) is not None
                ]
                relative = value - float(np.mean(peers))
                if row["tla"] in driver_values:
                    driver_values[row["tla"]].append(
                        (weight * share * (0.25 if older else 1), relative)
                    )
                for team, name in teams.items():
                    if name and row.get("team_name") == name:
                        team_values[team].append((weight * share * car_weight, value))
    field = [v for values in team_values.values() for _, v in values]
    field_mean = float(np.median(field)) if field else 0.0

    def mean(values, prior):
        return (params["prior"] * prior + sum(w * v for w, v in values)) / (
            params["prior"] + sum(w for w, _ in values)
        )

    team_means = {
        team: mean(values, field_mean) for team, values in team_values.items()
    }
    means = np.array(
        [team_means[d["team_id"]] + mean(driver_values[d["tla"]], 0) for d in drivers]
    )
    differences = [
        abs(a[1] - b[1])
        for values in driver_values.values()
        for a, b in zip(values, values[1:])
    ]
    # Consecutive-lap-margin MAD estimates observed event-to-event variability.
    # A field-resolution floor avoids zero variance in tiny/identical samples.
    scale = max(
        float(np.median(differences)) / 0.954 if differences else 0.0,
        float(np.ptp(means)) / max(2, len(drivers)),
        0.01,
    )
    noise = np.array(
        [
            np.sqrt(
                (
                    params["prior"] * scale**2
                    + sum(
                        w * (v - (means[i] - team_means[d["team_id"]])) ** 2
                        for w, v in driver_values[d["tla"]]
                    )
                )
                / (params["prior"] + sum(w for w, _ in driver_values[d["tla"]]))
            )
            for i, d in enumerate(drivers)
        ]
    )
    return means, noise, teams


def draw(records, drivers, simulations, rng, telemetry, params):
    from .racing_data import cause

    n = len(drivers)
    team_ids = sorted({str(d["team_id"]) for d in drivers})
    ti = np.array([team_ids.index(str(d["team_id"])) for d in drivers])
    team_shock = rng.normal(size=(simulations, len(team_ids)))[:, ti]
    driver_shock = rng.normal(size=(simulations, n))
    recent = records[-16:]
    weights = 2.0 ** (-np.arange(len(recent) - 1, -1, -1) / params["half_life"])
    weights /= weights.sum()
    sampled = rng.choice(len(recent), simulations, p=weights)
    output = {}
    kinds = (
        ["Q"]
        + (["SQ"] if any(r["sessions"].get("SQ") for r in records) else [])
        + ["R", "S"]
    )
    for kind in kinds:
        means, noise, teams = _form(records, drivers, kind, params)
        sigma = noise * params["temperature"]
        share = params["team_share"]
        shared = np.sqrt(share) * team_shock + np.sqrt((1 - share) / 2) * driver_shock
        performance = means + sigma * (
            shared + np.sqrt((1 - share) / 2) * rng.normal(size=(simulations, n))
        )
        # A historical wet/mixed/SC weekend supplies a shared regime, including
        # observed field-wide incident counts, rather than independent DNF coins.
        regimes = [
            r.get("session_context", {}).get(kind, {}).get("regime", "unknown")
            for r in recent
        ]
        wet_indices = [
            i for i, regime in enumerate(regimes) if regime in {"wet", "mixed"}
        ]
        wet_mask = np.isin(sampled, wet_indices)
        wet_diffs = [
            abs(row["pace_gap_pct"])
            for r in recent
            if r.get("session_context", {}).get(kind, {}).get("regime")
            in {"wet", "mixed"}
            for row in r["sessions"].get(kind, [])
            if row.get("pace_gap_pct") is not None
        ]
        if wet_diffs:
            wet_scale = max(float(np.median(wet_diffs)), float(np.median(sigma)))
            performance += wet_mask[:, None] * rng.normal(
                0, wet_scale, (simulations, n)
            )
        if kind in {"R", "S"}:
            grid_kind = "SQ" if kind == "S" and "SQ" in output else "Q"
            performance += (
                params["grid_weight"]
                * np.ptp(means)
                * (output[grid_kind]["ranks"] - 1)
                / max(1, n - 1)
            )
        # Existing Fantasy telemetry corrections are bounded and converted from
        # point units to an empirically measured pace spread, never seconds.
        delta = np.array(
            [
                telemetry.get((0, str(d["id"])), (0, 0, 0))[
                    ("Q", "S", "R").index("Q" if kind == "SQ" else kind)
                ]
                for d in drivers
            ]
        )
        performance -= np.clip(delta / 4, -2, 2) * np.median(noise) / 2
        exposures, failures = {t: 0.0 for t in team_ids}, {t: 0.0 for t in team_ids}
        for age, rec in enumerate(reversed(records[-24:])):
            w = 2 ** (-age / params["half_life"])
            for row in rec["sessions"].get(kind, []):
                for team in team_ids:
                    original = next(
                        d["team_id"] for d in drivers if str(d["team_id"]) == team
                    )
                    if row.get("team_name") == teams[original]:
                        reason = cause(row.get("status", ""))
                        if kind in {"R", "S"} and reason in {
                            "disqualified",
                            "did_not_start",
                        }:
                            continue
                        exposures[team] += w
                        failed = (
                            not row.get("qualified", True)
                            if kind in {"Q", "SQ"}
                            else not row["classified"] and reason == "mechanical"
                        )
                        failures[team] += w * failed
        pooled = (sum(failures.values()) + 0.5) / (sum(exposures.values()) + 1)
        reliability = np.column_stack(
            [
                rng.beta(
                    failures[t] + params["prior"] * pooled,
                    exposures[t] - failures[t] + params["prior"] * (1 - pooled),
                    simulations,
                )
                for t in team_ids
            ]
        )[:, ti]
        classified = rng.random((simulations, n)) >= reliability
        if kind in {"R", "S"}:
            incident_counts = [
                round(
                    n
                    * sum(
                        not row["classified"]
                        and cause(row.get("status", "")) != "mechanical"
                        for row in rec["sessions"].get(kind, [])
                    )
                    / max(1, len(rec["sessions"].get(kind, [])))
                )
                for rec in recent
            ]
            counts = np.array(incident_counts)[sampled]
            # One sampled event count is shared by the field. Drivers are chosen
            # without replacement, so a multi-car incident remains a joint event.
            order = np.argsort(rng.random((simulations, n)), axis=1)
            incident_rank = np.argsort(order, axis=1)
            classified &= incident_rank >= counts[:, None]
        performance += (~classified) * (
            np.ptp(means) + 100 + rng.random((simulations, n))
        )
        order = np.argsort(performance, axis=1, kind="stable")
        ranks = np.argsort(order, axis=1) + 1
        output[kind] = {"ranks": ranks, "classified": classified}
    # Timed best laps, fresh-tyre age and late stops replace winner-count/rank
    # weights when those measurements exist; race and Sprint stay separate.
    for kind, key in (("R", "fastest_lap"), ("S", "sprint_fastest_lap")):
        if kind == "S" and not any(r.get(key) for r in records):
            continue
        lap_values, opportunities, all_observations = [], [], []
        for d in drivers:
            observations = []
            for rec in records[-16:]:
                rows = rec["sessions"].get(kind, [])
                best = min(
                    (r["best_lap_seconds"] for r in rows if r.get("best_lap_seconds")),
                    default=None,
                )
                row = next((r for r in rows if r["tla"] == d["tla"]), {})
                if best and row.get("best_lap_seconds"):
                    gap = 100 * (row["best_lap_seconds"] / best - 1)
                    fresh_late = (
                        row.get("best_lap_tyre_age") is not None
                        and row["best_lap_tyre_age"] <= 3
                        and row.get("laps")
                        and row.get("best_lap_number", 0) >= 0.65 * row["laps"]
                    )
                    observations.append((gap, bool(fresh_late)))
            all_observations.extend(observations)
            lap_values.append(
                float(np.mean([v for v, _ in observations])) if observations else None
            )
            opportunities.append([o for _, o in observations])
        prior = (
            float(np.median([v for v in lap_values if v is not None]))
            if any(v is not None for v in lap_values)
            else 0.0
        )
        pace = np.array([v if v is not None else prior for v in lap_values])
        scale = max(float(np.std(pace)), 0.1)
        fl = pace + rng.gumbel(0, scale, (simulations, n))
        fresh = [v for v, o in all_observations if o]
        worn = [v for v, o in all_observations if not o]
        if fresh and worn:
            benefit = max(0.0, float(np.median(worn) - np.median(fresh)))
            rate = len(fresh) / len(all_observations)
            chances = np.array(
                [
                    (sum(v) + params["prior"] * rate) / (len(v) + params["prior"])
                    for v in opportunities
                ]
            )
            fl -= benefit * ((rng.random((simulations, n)) < chances) - chances)
        output[key] = np.argmin(fl, axis=1)
    return output


def baseline(records, drivers, simulations, rng, recent=False):
    n = len(drivers)
    output = {}
    for kind in ("Q", "R"):
        performance = 1 + n * rng.random((simulations, n))
        flags = np.ones((simulations, n), dtype=bool)
        form = [r for r in records if r["sessions"].get(kind)][-8:]
        if recent and form:
            sampled = rng.integers(len(form), size=simulations)
            use_history = rng.random(simulations) < len(form) / (len(form) + n)
            for j, record in enumerate(form):
                rows = {r["tla"]: r for r in record["sessions"][kind]}
                chosen = (sampled == j) & use_history
                for i, d in enumerate(drivers):
                    row = rows.get(d["tla"])
                    if row and row.get("position"):
                        performance[chosen, i] = (
                            row["position"] + rng.random(chosen.sum()) * 0.01
                        )
                        flags[chosen, i] = (
                            row.get("qualified", True)
                            if kind == "Q"
                            else row["classified"]
                        )
        output[kind] = {
            "ranks": np.argsort(np.argsort(performance, axis=1), axis=1) + 1,
            "classified": flags,
        }
    return output


def score(draws, target, drivers):
    scores = {}
    n = len(drivers)
    for kind, label in (("R", "winner"), ("Q", "pole")):
        rows = {r["tla"]: r for r in target["sessions"].get(kind, [])}
        if len(rows) != n or not any(r.get("position") == 1 for r in rows.values()):
            continue
        rank, flags = draws[kind]["ranks"], draws[kind]["classified"]
        actual = np.array([rows[d["tla"]]["position"] or n for d in drivers])
        qualified = np.array(
            [
                rows[d["tla"]].get("qualified", True)
                if kind == "Q"
                else rows[d["tla"]]["classified"]
                for d in drivers
            ]
        )
        p = ((rank == 1) & flags).mean(axis=0)
        winner = actual == 1
        scores[label + "_brier"] = float(np.sum((p - winner) ** 2))
        smooth = (p * len(rank) + 0.5) / (len(rank) + n * 0.5)
        scores[label + "_log_loss"] = float(-np.log(smooth[winner]).mean())
        if kind == "R":
            podium = ((rank <= 3) & flags).mean(axis=0)
            scores["podium_brier"] = float(
                np.mean((podium - ((actual <= 3) & qualified)) ** 2)
            )
            dist = np.column_stack(
                [
                    ((rank == position) & flags).mean(axis=0)
                    for position in range(1, n + 1)
                ]
                + [(~flags).mean(axis=0)]
            )
            outcomes = np.where(qualified, actual - 1, n).astype(int)
            truth = np.eye(n + 1)[np.clip(outcomes, 0, n)]
            scores["position_rps"] = float(
                np.mean(
                    (np.cumsum(dist, axis=1)[:, :-1] - np.cumsum(truth, axis=1)[:, :-1])
                    ** 2
                )
            )
            pairs = []
            for i in range(n):
                for j in range(i + 1, n):
                    if not (qualified[i] or qualified[j]):
                        continue
                    chance = np.mean(
                        flags[:, i] & ((rank[:, i] < rank[:, j]) | ~flags[:, j])
                    )
                    outcome = qualified[i] and (
                        actual[i] < actual[j] or not qualified[j]
                    )
                    pairs.append((chance - outcome) ** 2)
            scores["head_to_head_brier"] = float(np.mean(pairs)) if pairs else 0.0
            scores["winner_reliability"] = [
                [float(p[i]), int(winner[i])] for i in range(n)
            ]
    return scores


def objective(scores):
    return sum(
        scores.get(key, 1.0)
        for key in ("winner_brier", "pole_brier", "podium_brier", "head_to_head_brier")
    )


def averages(rows):
    return {
        key: float(np.mean([r[key] for r in rows if key in r]))
        for key in (
            "winner_brier",
            "winner_log_loss",
            "pole_brier",
            "pole_log_loss",
            "podium_brier",
            "head_to_head_brier",
            "position_rps",
        )
        if any(key in r for r in rows)
    }


def evaluate(records, *, simulations=600, seed=2026):
    from .predict_model import _rank_draw
    from .public_history import date

    records = sorted(records, key=lambda r: date(r["end"]))
    candidate_scores = [[] for _ in PARAMETERS]
    nested, comparisons, folds = [], {"rank_v1": [], "uniform": [], "last8": []}, []
    for index, target in enumerate(records):
        # Compact archived calendars retain only race start. An additional
        # 72-hour embargo keeps these historical folds pre-weekend.
        cutoff = date(target.get("race_start_utc", target["end"])) - timedelta(days=3)
        history = [r for r in records[:index] if date(r["end"]) < cutoff]
        if len(history) < 8 or not timed(history):
            continue
        drivers = roster(target)
        if len(drivers) < 3:
            continue
        # Parameter selection uses earlier scored folds only. The target's
        # identity list is a roster condition, never its positions/times/status.
        selected = min(
            range(len(PARAMETERS)),
            key=lambda i: (
                objective(averages(candidate_scores[i])) if candidate_scores[i] else i
            ),
        )
        scores = []
        for j, params in enumerate(PARAMETERS):
            prediction = draw(
                history,
                drivers,
                simulations,
                np.random.default_rng(seed + index),
                {},
                params,
            )
            scores.append(score(prediction, target, drivers))
        nested.append(scores[selected])
        for j, values in enumerate(scores):
            candidate_scores[j].append(values)
        for name in comparisons:
            rng = np.random.default_rng(seed + index)
            prediction = (
                _rank_draw(history, drivers, simulations, rng, {})
                if name == "rank_v1"
                else baseline(
                    history, drivers, simulations, rng, recent=name == "last8"
                )
            )
            comparisons[name].append(score(prediction, target, drivers))
        folds.append(
            {
                "season": target["season"],
                "round": target["round"],
                "cutoff": cutoff.isoformat(),
                "training_events": len(history),
                "parameter_training_folds": len(folds),
                "parameters": PARAMETERS[selected],
                "candidate": nested[-1],
                "baselines": {name: values[-1] for name, values in comparisons.items()},
            }
        )
    metrics = {
        "candidate": averages(nested),
        **{name: averages(values) for name, values in comparisons.items()},
    }
    params = PARAMETERS[
        min(
            range(len(PARAMETERS)),
            key=lambda i: (
                objective(averages(candidate_scores[i])) if candidate_scores[i] else i
            ),
        )
    ]
    valid = len(folds) >= 8
    candidate_wins = valid and all(
        objective(metrics["candidate"]) < objective(metrics[name])
        and metrics["candidate"].get("winner_brier", 1)
        < metrics[name].get("winner_brier", 1)
        for name in comparisons
    )
    selection = "margin_v2" if candidate_wins else "rank_v1"
    reliability = []
    for low in np.arange(0, 1, 0.1):
        values = [
            v
            for row in nested
            for v in row.get("winner_reliability", [])
            if low <= v[0] < low + 0.1
        ]
        if values:
            reliability.append(
                {
                    "low": float(round(low, 1)),
                    "count": len(values),
                    "mean_probability": float(np.mean([v[0] for v in values])),
                    "observed_rate": float(np.mean([v[1] for v in values])),
                }
            )
    return {
        "model": VERSION,
        "selected": selection,
        "parameters": params,
        "evaluated_events": len(folds),
        "metrics": metrics,
        "winner_reliability": reliability,
        "calibrated": False,
        "roster_condition": "Historical target entry identities/teams are supplied; target results, timings and weather are never features",
        "folds": folds,
    }


@lru_cache(maxsize=4)
def _selection(encoded):
    report = evaluate(json.loads(encoded))
    return {k: v for k, v in report.items() if k != "folds"}


def selection(records):
    if not timed(records):
        return {
            "model": VERSION,
            "selected": "rank_v1",
            "evaluated_events": 0,
            "calibrated": False,
            "reason": "Insufficient verified lap-margin coverage; legacy model retained",
        }
    return _selection(json.dumps(records, sort_keys=True, allow_nan=False))
