"""One walk-forward backtest for every racing-model variant.

    python -m f1fantasy.model_compare [--simulations 1000] [--output data/model-comparison.json]

All variants are scored on the same folds (same cutoffs, 72 h embargo, same
metrics) so differences are paired. Each tuned family picks its hyper-parameters
*nested*: before scoring race k it chooses the configuration with the best mean
objective over races < k, so the reported numbers never use a race to tune the
model that predicts it. ``pre`` variants use only information available before
the weekend; ``post-quali`` variants also condition on the known starting grid
and must not be compared with ``pre`` variants as if they were the same product.
"""

from __future__ import annotations

import argparse
import contextlib
import json
from datetime import timedelta
from itertools import product
from pathlib import Path

import numpy as np

from . import public_history, racing_model, race_model
from .predict_model import _rank_draw
from .public_history import date

NC_WEIGHT = 1.0  # nc_brier enters the selection objective alongside the other four


def objective(row: dict) -> float:
    return racing_model.objective(row) + NC_WEIGHT * row.get("nc_brier", 1.0)


def starting_grid(record: dict) -> dict[str, int]:
    """Actual starting positions (penalties included); qualifying order if absent."""
    rows = record["sessions"]["R"]
    if sum(bool(r.get("grid")) for r in rows) >= len(rows) - 2:
        # Pit-lane starters have no grid number; put them behind the field.
        worst = len(rows) + 1
        return {r["tla"]: int(r.get("grid") or worst) for r in rows}
    return {
        r["tla"]: int(r["position"])
        for r in record["sessions"]["Q"]
        if r.get("position")
    }


@contextlib.contextmanager
def retirement(half_life: float, prior: float):
    old = racing_model.RETIREMENT_HALF_LIFE, racing_model.RETIREMENT_PRIOR
    racing_model.RETIREMENT_HALF_LIFE, racing_model.RETIREMENT_PRIOR = half_life, prior
    try:
        yield
    finally:
        racing_model.RETIREMENT_HALF_LIFE, racing_model.RETIREMENT_PRIOR = old


# --- variant definitions ------------------------------------------------------
# Each variant is (info, configs, predict). ``predict`` returns draws in the
# racing_model structure so racing_model.score can evaluate every family alike.


def _v2(uniform_retirement):
    def predict(history, drivers, target, sims, rng, cfg):
        with retirement(6.0, 1e9 if uniform_retirement else 16.0):
            return racing_model.draw(history, drivers, sims, rng, {}, cfg)

    return predict


def _v2_grid(history, drivers, target, sims, rng, cfg):
    with retirement(6.0, 16.0):
        return racing_model.draw(
            history, drivers, sims, rng, {}, cfg, grid=starting_grid(target)
        )


def _pl(history, drivers, target, sims, rng, cfg):
    return race_model.draw(history, drivers, sims, rng, season=target["season"], config=cfg)


def _pl_grid(history, drivers, target, sims, rng, cfg):
    return race_model.draw(
        history,
        drivers,
        sims,
        rng,
        season=target["season"],
        config=cfg,
        grid=starting_grid(target),
    )


def _v2_params(**grid):
    keys = list(grid)
    base = {"half_life": 2.0, "temperature": 0.8, "team_share": 0.35, "grid_weight": 0.0, "prior": 4.0}
    return [{**base, **dict(zip(keys, values))} for values in product(*grid.values())]


def _pl_configs(post: bool, **grid):
    from dataclasses import replace

    base = race_model.RaceModelConfig.post_qualifying() if post else race_model.RaceModelConfig()
    keys = list(grid)
    return [replace(base, **dict(zip(keys, values))) for values in product(*grid.values())]


def variants():
    return {
        "v2 (before NC change)": ("pre", _v2_params(half_life=(2.0, 4.0, 6.0), temperature=(0.6, 0.8, 1.0), team_share=(0.35, 0.7)), _v2(True)),
        "v2 + team-weighted NC": ("pre", _v2_params(half_life=(2.0, 4.0, 6.0), temperature=(0.6, 0.8, 1.0), team_share=(0.35, 0.7)), _v2(False)),
        "v2 + actual grid": ("post-quali", _v2_params(half_life=(2.0, 4.0), temperature=(1.0, 1.25), team_share=(0.35, 0.7), grid_weight=(1.5, 2.5, 3.5)), _v2_grid),
        "Plackett-Luce": ("pre", _pl_configs(False, half_life=(2.0, 3.0, 6.0), scale=(0.8, 1.0, 1.3), team_shock=(0.0, 0.4)), _pl),
        "Plackett-Luce + actual grid": ("post-quali", _pl_configs(True, half_life=(2.0, 3.0, 6.0), scale=(0.8, 1.0, 1.3), team_shock=(0.0, 0.4)), _pl_grid),
    }


def baselines(history, drivers, sims, rng, name):
    if name == "rank model v1 (shipped before v2)":
        return _rank_draw(history, drivers, sims, rng, {})
    return racing_model.baseline(history, drivers, sims, rng, recent=name == "last 8 races")


BASELINES = ("uniform", "last 8 races", "rank model v1 (shipped before v2)")


def row_metrics(draws, target, drivers):
    row = racing_model.score(draws, target, drivers)
    flags = draws["R"]["classified"]
    p = 1 - flags.mean(0)
    y = np.array([float(not r["classified"]) for r in target["sessions"]["R"]])
    # score() orders by roster(target), which is target order too.
    teams: dict = {}
    for j, r in enumerate(target["sessions"]["R"]):
        teams.setdefault(r.get("team_name"), []).append(j)
    either_p = np.array([(~flags[:, ix]).any(1).mean() for ix in teams.values()])
    either_y = np.array([float(y[ix].any()) for ix in teams.values()])
    row.update(
        nc_brier=float(((p - y) ** 2).mean()),
        either_nc_brier=float(((either_p - either_y) ** 2).mean()),
        nc_predicted=float(p.mean()),
        nc_observed=float(y.mean()),
    )
    return row


def folds(records):
    out = []
    for index, target in enumerate(records):
        cutoff = date(target.get("race_start_utc", target["end"])) - timedelta(days=3)
        history = [r for r in records[:index] if date(r["end"]) < cutoff]
        if len(history) < 8 or not racing_model.timed(history):
            continue
        if len(racing_model.roster(target)) < 3:
            continue
        out.append((index, target, history))
    return out


METRICS = (
    "winner_brier",
    "winner_log_loss",
    "pole_brier",
    "podium_brier",
    "head_to_head_brier",
    "position_rps",
    "nc_brier",
    "either_nc_brier",
)


def run(records, simulations=1000, seed=2026):
    records = sorted(records, key=lambda r: date(r["end"]))
    plan = folds(records)
    results: dict[str, dict] = {}
    for name in BASELINES:
        rows = []
        for index, target, history in plan:
            drivers = racing_model.roster(target)
            rng = np.random.default_rng(seed + index)
            rows.append(row_metrics(baselines(history, drivers, simulations, rng, name), target, drivers))
        results[name] = {"info": "pre", "rows": rows, "selected": None}
    for name, (info, configs, predict) in variants().items():
        grid_rows = [[] for _ in configs]
        nested, chosen = [], []
        for index, target, history in plan:
            drivers = racing_model.roster(target)
            pick = min(
                range(len(configs)),
                key=lambda i: np.mean([objective(r) for r in grid_rows[i]]) if grid_rows[i] else i,
            )
            fold_rows = []
            for cfg in configs:
                rng = np.random.default_rng(seed + index)
                fold_rows.append(row_metrics(predict(history, drivers, target, simulations, rng, cfg), target, drivers))
            for i, r in enumerate(fold_rows):
                grid_rows[i].append(r)
            nested.append(fold_rows[pick])
            chosen.append(pick)
        best = min(range(len(configs)), key=lambda i: np.mean([objective(r) for r in grid_rows[i]]))
        describe = (lambda c: c) if isinstance(configs[0], dict) else (lambda c: {k: v for k, v in c.__dict__.items()})
        results[name] = {
            "info": info,
            "rows": nested,
            "selected": describe(configs[best]),
            "in_sample_best_rows": grid_rows[best],
            "selection_counts": {str(describe(configs[i])): chosen.count(i) for i in sorted(set(chosen))},
            "all_configs": [
                {"config": describe(c), "objective": float(np.mean([objective(r) for r in grid_rows[i]]))}
                for i, c in enumerate(configs)
            ],
        }
    return plan, results


def mean(rows, key):
    values = [r[key] for r in rows if key in r]
    return float(np.mean(values)) if values else float("nan")


def paired(a, b, key, seed=0):
    pairs = [(x[key], y[key]) for x, y in zip(a, b) if key in x and key in y]
    diff = np.array([y - x for x, y in pairs])
    boots = np.random.default_rng(seed).choice(diff, (4000, len(diff))).mean(1)
    return float(diff.mean()), float(np.quantile(boots, 0.05)), float(np.quantile(boots, 0.95))


def report(plan, results, reference="v2 (before NC change)"):
    summary = {
        name: {k: mean(v["rows"], k) for k in METRICS}
        | {"nc_predicted": mean(v["rows"], "nc_predicted"), "nc_observed": mean(v["rows"], "nc_observed"), "information": v["info"], "selected": v["selected"]}
        for name, v in results.items()
    }
    versus = {
        name: {k: dict(zip(("mean", "lo90", "hi90"), paired(results[reference]["rows"], v["rows"], k))) for k in METRICS}
        for name, v in results.items()
        if name != reference
    }
    return {
        "folds": len(plan),
        "first": [plan[0][1]["season"], plan[0][1]["round"]],
        "last": [plan[-1][1]["season"], plan[-1][1]["round"]],
        "reference": reference,
        "summary": summary,
        "paired_vs_reference": versus,
        "selection_counts": {n: v.get("selection_counts") for n, v in results.items()},
        "all_configs": {n: v.get("all_configs") for n, v in results.items()},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("data/model-comparison.json"))
    args = parser.parse_args(argv)
    with public_history.repository(args.history) as document:
        plan, results = run(document["racing"], args.simulations)
    out = report(plan, results)
    args.output.write_text(json.dumps(out, indent=2, allow_nan=False, default=float) + "\n")
    width = max(map(len, out["summary"]))
    print(f"{out['folds']} folds, rounds {out['first']} to {out['last']}")
    print(f"{'':{width}}  " + "  ".join(f"{k[:10]:>10}" for k in METRICS))
    for name, s in out["summary"].items():
        print(f"{name:{width}}  " + "  ".join(f"{s[k]:10.4f}" for k in METRICS) + f"  [{s['information']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
