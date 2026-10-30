"""Walk-forward check of the not-classified (NC) probabilities.

    python -m f1fantasy.nc_walkforward [--history data/history.json] [--seasons 2025 2026]

For every target race only earlier races are used. Compares the racing model's
per-driver NC probability with (a) the same model without team weighting (a very
large pooling prior reproduces the former uniform assignment) and (b) simple
reference rates, and reports calibration of the level, the per-driver Brier
score, the "either car of a team is not classified" Brier score, and whether
win/podium/position scores moved.
"""

from __future__ import annotations

import argparse
import collections
import json

import numpy as np

from f1fantasy import racing_model
from f1fantasy.public_history import date

PARAMS = {"half_life": 2.0, "temperature": 0.8, "team_share": 0.35, "grid_weight": 0.0, "prior": 4.0}


def targets(records, seasons):
    return [i for i, r in enumerate(records) if r["season"] in seasons and i >= 8]


def evaluate(records, indices, prior, simulations):
    """Per-race metrics for one retirement pooling prior."""
    racing_model.RETIREMENT_PRIOR = prior
    rows = []
    for i in indices:
        target, drivers = records[i], racing_model.roster(records[i])
        out = racing_model.draw(
            records[:i], drivers, simulations, np.random.default_rng(7 + i), {}, PARAMS
        )
        nc = ~out["R"]["classified"]
        p = nc.mean(0)
        y = np.array([float(not r["classified"]) for r in target["sessions"]["R"]])
        teams = collections.defaultdict(list)
        for j, r in enumerate(target["sessions"]["R"]):
            teams[r["team_name"]].append(j)
        either_p = np.array([nc[:, ix].any(1).mean() for ix in teams.values()])
        either_y = np.array([float(y[ix].any()) for ix in teams.values()])
        row = racing_model.score(out, target, drivers)
        row.update(
            nc_brier=float(((p - y) ** 2).mean()),
            either_brier=float(((either_p - either_y) ** 2).mean()),
            predicted=float(p.mean()),
            observed=float(y.mean()),
            season=target["season"],
        )
        rows.append(row)
    return rows


def paired(old, new, key, seed=0):
    pairs = [(a[key], b[key]) for a, b in zip(old, new) if key in a and key in b]
    diff = np.array([b - a for a, b in pairs])
    means = np.random.default_rng(seed).choice(diff, (4000, len(diff))).mean(1)
    return diff.mean(), np.quantile(means, 0.05), np.quantile(means, 0.95)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", default="data/history.json")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--simulations", type=int, default=2000)
    args = parser.parse_args()
    records = sorted(
        json.load(open(args.history))["racing"], key=lambda r: date(r["end"])
    )
    indices = targets(records, set(args.seasons))
    shipped = racing_model.RETIREMENT_PRIOR
    try:
        uniform = evaluate(records, indices, 1e9, args.simulations)
        weighted = evaluate(records, indices, shipped, args.simulations)
    finally:
        racing_model.RETIREMENT_PRIOR = shipped
    print(f"{len(indices)} races; level (mean predicted vs observed NC per driver)")
    for name, rows in (("uniform assignment", uniform), ("team-weighted", weighted)):
        print(
            f"  {name:20s} predicted {np.mean([r['predicted'] for r in rows]):.3f} "
            f"observed {np.mean([r['observed'] for r in rows]):.3f} "
            f"Brier {np.mean([r['nc_brier'] for r in rows]):.4f} "
            f"either-car Brier {np.mean([r['either_brier'] for r in rows]):.4f}"
        )
    print("paired difference, team-weighted minus uniform (90% bootstrap interval):")
    for key in ("nc_brier", "either_brier", "winner_brier", "podium_brier", "head_to_head_brier", "position_rps"):
        m, lo, hi = paired(uniform, weighted, key)
        print(f"  {key:20s} {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")


if __name__ == "__main__":
    main()
