"""Scheduled, gated fitting of the racing-model parameters.

    python -m f1fantasy.model_fit [--history data/history.json] [--output data/model-params.json]

Each run evaluates the *current* parameters and their one-step neighbours on the
same walk-forward folds as ``model_compare`` (races predicted only from earlier
races, 72 h embargo). A change is adopted only when all of these hold:

1. the best neighbour, chosen on the older folds only, improves the objective by
   at least ``MIN_GAIN`` there;
2. it does not do worse than the current parameters on the most recent
   ``HOLDOUT`` races, which were not used to choose it;
3. it improves the full-sample paired mean by at least ``MIN_GAIN``.

So parameters move at most one step per run, never on noise, and keep improving as
races accumulate. Practice weights are fitted the same way once at least
``MIN_PRACTICE_FOLDS`` archived races carry ``practice_pace``. The result, the
evidence for it and a short log are written to ``data/model-params.json``, which
``racing_model`` loads (ignoring it if it is missing or out of range).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import model_compare as mc
from . import practice as practice_model
from . import public_history, racing_model

MIN_GAIN = 0.005  # objective is a sum of five Brier-type scores (about 2.0)
HOLDOUT = 12
MIN_FOLDS = 24
MIN_PRACTICE_FOLDS = 12
LOG_LENGTH = 30

# One-step ladders. A value off the ladder snaps to its nearest rung first.
LADDERS = {
    "half_life": (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0),
    "temperature": (0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0),
    "team_share": (0.2, 0.35, 0.5, 0.7, 0.85),
    "prior": (2.0, 4.0, 8.0, 16.0),
    "grid_weight": (0.3, 0.6, 1.0, 1.5, 2.5, 3.5, 5.0),
    "ret_half_life": (3.0, 6.0, 12.0),
    "ret_prior": (8.0, 16.0, 32.0),
}
FAMILY_DIMS = {
    "pre": ("half_life", "temperature", "team_share", "prior", "ret_half_life", "ret_prior"),
    "post": ("half_life", "temperature", "team_share", "grid_weight", "ret_half_life", "ret_prior"),
}
PRACTICE_LADDER = (0.0, 0.1, 0.15, 0.25, 0.4)


def snap(value, ladder):
    return min(range(len(ladder)), key=lambda i: abs(ladder[i] - value))


def neighbours(params, dims):
    """Parameter sets that differ from ``params`` by one rung in one dimension."""
    out = []
    for dim in dims:
        ladder = LADDERS[dim]
        index = snap(params.get(dim, ladder[len(ladder) // 2]), ladder)
        for step in (-1, 1):
            if 0 <= index + step < len(ladder):
                out.append({**params, dim: ladder[index + step]})
    return out


def with_defaults(params, family):
    base = {**(racing_model.DEFAULT_PRE if family == "pre" else racing_model.DEFAULT_POST)}
    base.setdefault("ret_half_life", racing_model.DEFAULT_RETIREMENT["half_life"])
    base.setdefault("ret_prior", racing_model.DEFAULT_RETIREMENT["prior"])
    return {**base, **params}


def evaluate(plan, params, family, simulations, seed=2026, practice_key=None):
    """Per-fold metric rows for one parameter set."""
    rows = []
    for index, target, history in plan:
        drivers = racing_model.roster(target)
        rng = np.random.default_rng(seed + index)
        if family == "post":
            draws = racing_model.draw(
                history, drivers, simulations, rng, {}, params, grid=mc.starting_grid(target)
            )
        else:
            extra = {}
            if practice_key:
                extra["practice"] = practice_from_record(target)
            draws = racing_model.draw(history, drivers, simulations, rng, {}, params, **extra)
        rows.append(mc.row_metrics(draws, target, drivers))
    return rows


def practice_from_record(record):
    """Field-centred practice pace archived for a race (all its practice sessions)."""
    return practice_model.combine(record.get("practice_pace") or {})


def mean_objective(rows):
    return float(np.mean([mc.objective(r) for r in rows]))


def decide(rows_by_candidate, current_key, holdout=HOLDOUT):
    """Apply the three-part gate. ``rows_by_candidate`` maps key -> fold rows.

    Returns (chosen_key, verdict dict). ``chosen_key`` equals ``current_key`` when
    nothing is adopted.
    """
    current = rows_by_candidate[current_key]
    n = len(current)
    split = n - min(holdout, n // 3)
    others = [k for k in rows_by_candidate if k != current_key]
    verdict = {"folds": n, "holdout_folds": n - split, "adopted": False, "reason": ""}
    if n < MIN_FOLDS or not others:
        verdict["reason"] = f"Too few evaluated races ({n}; need {MIN_FOLDS})"
        return current_key, verdict
    train = lambda rows: mean_objective(rows[:split])
    best = min(others, key=lambda k: train(rows_by_candidate[k]))
    rows = rows_by_candidate[best]
    gain_train = train(current) - train(rows)
    gain_hold = mean_objective(current[split:]) - mean_objective(rows[split:])
    gain_all = mean_objective(current) - mean_objective(rows)
    diffs = np.array([mc.objective(b) - mc.objective(a) for a, b in zip(current, rows)])
    boots = np.random.default_rng(0).choice(diffs, (2000, len(diffs))).mean(1)
    verdict.update(
        candidate=best,
        gain_train=gain_train,
        gain_holdout=gain_hold,
        gain_all=gain_all,
        interval90=[float(np.quantile(boots, 0.05)), float(np.quantile(boots, 0.95))],
    )
    if gain_train < MIN_GAIN:
        verdict["reason"] = "No neighbouring setting beats the current one on the older races"
    elif gain_hold < 0:
        verdict["reason"] = "Best neighbour is worse than the current setting on the latest races"
    elif gain_all < MIN_GAIN:
        verdict["reason"] = "Full-sample gain is below the minimum"
    else:
        verdict["adopted"] = True
        verdict["reason"] = "Adopted: better on older races, not worse on the latest, gain over the minimum"
        return best, verdict
    return current_key, verdict


def key_of(params):
    return json.dumps(params, sort_keys=True)


def fit_family(plan, family, current, simulations):
    dims = FAMILY_DIMS[family]
    current = with_defaults(current, family)
    candidates = {key_of(current): current}
    for candidate in neighbours(current, dims):
        candidates[key_of(candidate)] = candidate
    rows = {k: evaluate(plan, p, family, simulations) for k, p in candidates.items()}
    chosen, verdict = decide(rows, key_of(current))
    defaults = with_defaults({}, family)
    default_rows = rows.get(key_of(defaults)) or evaluate(plan, defaults, family, simulations)
    after_rows = rows[chosen]
    diffs = np.array([mc.objective(b) - mc.objective(a) for a, b in zip(default_rows, after_rows)])
    boots = np.random.default_rng(1).choice(diffs, (2000, len(diffs))).mean(1)
    summary = {
        "params": candidates[chosen],
        "objective": mean_objective(after_rows),
        "defaults_objective": mean_objective(default_rows),
        "gain_vs_defaults": float(-diffs.mean()),
        "gain_vs_defaults_interval90": [float(-np.quantile(boots, 0.95)), float(-np.quantile(boots, 0.05))],
        "metrics": {k: mc.mean(after_rows, k) for k in mc.METRICS},
        "default_metrics": {k: mc.mean(default_rows, k) for k in mc.METRICS},
        "decision": verdict,
    }
    return summary


def fit_practice(records, current, simulations):
    """Fit practice weights on races that archived practice pace (pre-weekend family)."""
    with_practice = [r for r in records if r.get("practice_pace")]
    status = {"races_with_practice": len(with_practice), "needed": MIN_PRACTICE_FOLDS}
    plan = [
        item
        for item in mc.folds(records)
        if item[1].get("practice_pace") and practice_from_record(item[1])
    ]
    status["folds"] = len(plan)
    if len(plan) < MIN_PRACTICE_FOLDS:
        status["status"] = f"waiting for data: {len(plan)} of {MIN_PRACTICE_FOLDS} races carry practice pace"
        return {"weights": current, **status}
    base_params = {**racing_model.PRE_PARAMETERS}

    def run(weights):
        params = {**base_params, "practice_weight": weights}
        return evaluate(plan, params, "pre", simulations, practice_key=True)

    candidates = {key_of(current): current}
    for kind in ("Q", "R"):
        index = snap(current[kind], PRACTICE_LADDER)
        for step in (-1, 1):
            if 0 <= index + step < len(PRACTICE_LADDER):
                candidate = {**current, kind: PRACTICE_LADDER[index + step]}
                if kind == "Q":
                    candidate["SQ"] = candidate["Q"]
                candidates[key_of(candidate)] = candidate
    rows = {k: run(w) for k, w in candidates.items()}
    none_rows = run({"Q": 0.0, "SQ": 0.0, "R": 0.0})
    chosen, verdict = decide(rows, key_of(current))
    gain = mean_objective(none_rows) - mean_objective(rows[chosen])
    return {
        "weights": candidates[chosen],
        "gain_vs_no_practice": float(gain),
        "decision": verdict,
        **status,
        "status": "fitted",
    }


def load_records(path):
    with public_history.repository(path) as document:
        return sorted(document["racing"], key=lambda r: public_history.date(r["end"]))


def accuracy(metrics):
    """Plain-language score: 100 minus the average finishing-order error, in percent."""
    rps = (metrics or {}).get("position_rps")
    return round(100 * (1 - rps), 1) if rps is not None else None


def fit(records, previous=None, simulations=600, now=None):
    now = now or datetime.now(timezone.utc)
    previous = previous or {}
    plan = mc.folds(records)
    current_pre = previous.get("pre", {}).get("params") or racing_model.DEFAULT_PRE
    current_post = previous.get("post_qualifying", {}).get("params") or racing_model.DEFAULT_POST
    current_practice = previous.get("practice", {}).get("weights") or racing_model.DEFAULT_PRACTICE
    last = plan[-1][1] if plan else None
    document = {
        "schema": 1,
        "fitted_at": now.isoformat(),
        "evaluated_races": len(plan),
        "last_race": [last["season"], last["round"]] if last else None,
        "simulations": simulations,
        "gate": {"min_gain": MIN_GAIN, "holdout_races": HOLDOUT, "min_races": MIN_FOLDS},
        "pre": fit_family(plan, "pre", current_pre, simulations),
        "post_qualifying": fit_family(plan, "post", current_post, simulations),
        "practice": fit_practice(records, current_practice, simulations),
    }
    log = list(previous.get("log", []))
    entry = {"at": now.isoformat(), "races": len(plan)}
    for family in ("pre", "post_qualifying"):
        decision = document[family]["decision"]
        entry[family] = {
            "adopted": decision["adopted"],
            "reason": decision["reason"],
            "params": document[family]["params"],
            "gain_vs_defaults": document[family]["gain_vs_defaults"],
            "accuracy": accuracy(document[family].get("metrics")),
        }
    document["log"] = (log + [entry])[-LOG_LENGTH:]
    return document


def unchanged(previous, document):
    """True when a run found nothing new (so the file need not be rewritten)."""
    if not previous:
        return False
    keys = lambda d: (
        d.get("last_race"),
        d["pre"]["params"],
        d["post_qualifying"]["params"],
        d["practice"]["weights"],
    )
    return keys(previous) == keys(document)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument("--output", type=Path, default=racing_model.PARAMS_FILE)
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument(
        "--force", action="store_true", help="refit even if no new race has finished"
    )
    args = parser.parse_args(argv)
    records = load_records(args.history)
    try:
        previous = json.loads(args.output.read_text())
    except (OSError, ValueError):
        previous = None
    plan = mc.folds(records)
    latest = [plan[-1][1]["season"], plan[-1][1]["round"]] if plan else None
    if previous and not args.force and previous.get("last_race") == latest:
        # One step per newly completed race: refitting on the same races would
        # reuse the same hold-out repeatedly and drift toward fitting noise.
        print(f"No new race since {latest}; parameters stay as fitted.")
        return 0
    document = fit(records, previous, args.simulations)
    if unchanged(previous, document):
        print("No new races and no parameter change; leaving the fit file as it is.")
        return 0
    args.output.write_text(json.dumps(document, indent=2, allow_nan=False, default=float) + "\n")
    for family in ("pre", "post_qualifying"):
        f = document[family]
        print(
            f"{family}: {f['decision']['reason']} | params {f['params']} | "
            f"gain vs defaults {f['gain_vs_defaults']:+.4f} {f['gain_vs_defaults_interval90']}"
        )
    print(f"practice: {document['practice']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
