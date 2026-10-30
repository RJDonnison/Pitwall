"""Stationary-time distributions, correlated opportunities and honest fallbacks."""

from collections import Counter

import numpy as np

from .public_history import date


def simulate(events, teams, key, *, simulations=4000, seed=2026, half_life=12, prior=8):
    rng = np.random.default_rng(seed)
    weights = 2.0 ** (-np.arange(len(events) - 1, -1, -1) / half_life)
    logs = [
        (w, key(s["team_name"]), np.log(s["seconds"]))
        for w, e in zip(weights, events)
        for s in e["stops"]
        if np.isfinite(s["seconds"]) and s["seconds"] > 0
    ]
    field = np.array([v for _, _, v in logs])
    # Extended repair/red-flag services are not the normal-service distribution.
    # Its robust centre/tail, not lane time, determines the minimum stop.
    centre = float(np.median(field))
    spread = max(float(np.subtract(*np.quantile(field, [0.75, 0.25]))) / 1.349, 0.02)
    sampled = rng.choice(len(events), simulations, p=weights / weights.sum())
    times = []
    for team in teams:
        values = [
            (w, v) for w, t, v in logs if t == team and abs(v - centre) <= 3 * spread
        ]
        mass = sum(w for w, _ in values)
        mean = (prior * centre + sum(w * v for w, v in values)) / (prior + mass)
        variance = (prior * spread**2 + sum(w * (v - mean) ** 2 for w, v in values)) / (
            prior + mass
        )
        # Bootstrap whole race opportunity counts. Shared weather/SC/strategy
        # changes in historical races therefore affect all crews together.
        counts = np.array(
            [sum(key(s["team_name"]) == team for s in e["stops"]) for e in events]
        )
        if not counts.any():
            all_counts = [
                list(Counter(key(s["team_name"]) for s in e["stops"]).values())
                for e in events
            ]
            counts = np.array([round(np.mean(c)) if c else 0 for c in all_counts])
        counts = counts[sampled]
        maximum = int(counts.max())
        stops = rng.lognormal(mean, np.sqrt(variance), (simulations, maximum))
        stops[np.arange(maximum)[None, :] >= counts[:, None]] = np.inf
        times.append(stops.min(axis=1) if maximum else np.full(simulations, np.inf))
    times = np.column_stack(times)
    valid = np.isfinite(times).any(axis=1)
    wins = np.bincount(times[valid].argmin(axis=1), minlength=len(teams))
    # Jeffreys smoothing prevents finite simulations declaring impossibility.
    probabilities = (wins + 0.5) / (valid.sum() + 0.5 * len(teams))
    return {t: float(p) for t, p in zip(teams, probabilities)}


def forecast(document, assets, cutoff, season, team_key):
    teams = [a for a in assets if a.kind == "CONSTRUCTOR"]
    names = [team_key(a.name) for a in teams]
    events = sorted(
        (
            e
            for e in document.get("stationary_stops", [])
            if date(e["end"]) < cutoff
            and e["season"] >= season - 2
            and all(date(s["date"]) < cutoff for s in e["stops"])
        ),
        key=lambda e: date(e["end"]),
    )
    if len(events) < 4:
        return None
    scores = {"stationary": [], "frequency": [], "uniform": []}
    for index in range(8, len(events)):
        target = events[index]
        history = events[:index]
        record = next(
            (
                r
                for r in document.get("racing", [])
                if (r["season"], r["round"]) == (target["season"], target["round"])
            ),
            None,
        )
        if record is None:
            continue
        target_teams = sorted(
            {team_key(r["team_name"]) for r in record["sessions"]["R"]}
        )
        if set(target_teams) != {team_key(s["team_name"]) for s in target["stops"]}:
            continue  # incomplete crew timing cannot identify the field winner
        minimum = min(s["seconds"] for s in target["stops"])
        winners = {
            team_key(s["team_name"]) for s in target["stops"] if s["seconds"] == minimum
        }
        if len(winners) != 1:
            continue  # rounded timing dead-heats do not establish a unique label
        p = simulate(history, target_teams, team_key, simulations=600)
        previous = Counter(
            team_key(min(e["stops"], key=lambda s: s["seconds"])["team_name"])
            for e in history[-8:]
        )
        frequency = {
            t: (1 + previous[t])
            / (len(target_teams) + sum(previous[t] for t in target_teams))
            for t in target_teams
        }
        for label, forecast in (
            ("stationary", p),
            ("frequency", frequency),
            ("uniform", {t: 1 / len(target_teams) for t in target_teams}),
        ):
            scores[label].append(
                sum((forecast[t] - int(t in winners)) ** 2 for t in target_teams)
            )
    averages = {k: float(np.mean(v)) if v else None for k, v in scores.items()}
    if len(scores["stationary"]) < 8 or not all(
        averages["stationary"] < averages[b] for b in ("frequency", "uniform")
    ):
        return {
            "status": "rejected",
            "evaluation": {
                "events": len(scores["stationary"]),
                "brier": averages,
                "reason": "Insufficient complete unique-winner folds or stationary model did not beat both baselines",
            },
        }
    p = simulate(events, names, team_key)
    return {
        "status": "ready",
        "model": "stationary-lognormal-opportunity-bootstrap-v1",
        "samples": len(events),
        "stop_samples": sum(len(e["stops"]) for e in events),
        "prior_per_team": None,
        "checked_at": document.get("updated_at"),
        "source": "https://openf1.org/docs/#pit",
        "evidence": [
            {
                "gameday_id": e["round"],
                "team_name": min(e["stops"], key=lambda s: s["seconds"])["team_name"],
                "published_at": e["end"],
            }
            for e in events[-8:]
        ],
        "probabilities": {a.id: p[team_key(a.name)] for a in teams},
        "evaluation": {
            "events": len(scores["stationary"]),
            "brier": averages,
            "tie_policy": "Unique measured fastest crews only; rounded dead-heats excluded",
        },
        "calibrated": False,
    }
