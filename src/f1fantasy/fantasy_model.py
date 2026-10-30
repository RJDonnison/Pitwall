"""Chronologically gated Fantasy totals from joint racing features and official labels.

The public feed supplies session totals, not all category details. Regression
learns their combined contribution; it does not invent overtakes or DOTD labels.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path

import numpy as np

from . import public_history, racing_model
from .data import Asset, Weekend

VERSION = "joint-features-official-fantasy-ridge-v1"
CONFIGS = [(half, ridge) for half in (2.0, 6.0, 12.0) for ridge in (1.0, 10.0, 100.0)]


def _recent(labels, asset, kind):
    values = [r["y"] for r in labels if r["id"] == asset and r["session"] == kind]
    return float(np.mean(values[-3:])) if values else 0.0


def _features(assets, weekend, history, labels, parameters, telemetry, seed):
    from .insights import _team_key
    from .telemetry_model import adjustments

    drivers = [a for a in assets if a.kind == "DRIVER"]
    roster = [
        dict(id=a.id, tla=a.tla, name=a.name, team_id=a.team_id, season=weekend.season)
        for a in drivers
    ]
    delta = adjustments(assets, [weekend]) if telemetry else {}
    draws = racing_model.draw(
        history, roster, 1200, np.random.default_rng(seed), delta, parameters
    )
    result = {}
    for kind in ("Q", "S", "R"):
        if kind == "S" and not weekend.sprint:
            continue
        ranks, classified = draws[kind]["ranks"], draws[kind]["classified"]
        table = (
            (10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
            if kind == "Q"
            else (8, 7, 6, 5, 4, 3, 2, 1)
            if kind == "S"
            else (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
        )
        finish = np.zeros(ranks.shape)
        for position, points in enumerate(table, 1):
            finish += (ranks == position) * points
        finish = np.where(
            classified, finish, -5 if kind == "Q" else -10 if kind == "S" else -20
        )
        grid = draws.get("SQ", draws["Q"]) if kind == "S" else draws["Q"]
        gain = (
            np.where(classified, grid["ranks"] - ranks, 0)
            if kind != "Q"
            else np.zeros(ranks.shape)
        )
        if kind == "S":
            gain = np.maximum(-10, gain)
        fastest = (
            draws.get("fastest_lap" if kind == "R" else "sprint_fastest_lap")
            if kind != "Q"
            else None
        )
        for asset in assets:
            indices = (
                [i for i, d in enumerate(drivers) if d.id == asset.id]
                if asset.kind == "DRIVER"
                else [i for i, d in enumerate(drivers) if d.team_id == asset.team_id]
            )
            if not indices:
                continue
            # Both-car advancement uses each joint qualifying draw, never the
            # threshold of two average driver scores.
            both_q3 = (
                float(
                    np.mean(
                        np.all(
                            (ranks[:, indices] <= 10) & classified[:, indices], axis=1
                        )
                    )
                )
                if kind == "Q" and asset.kind == "CONSTRUCTOR"
                else 0.0
            )
            any_q3 = (
                float(
                    np.mean(
                        np.any(
                            (ranks[:, indices] <= 10) & classified[:, indices], axis=1
                        )
                    )
                )
                if kind == "Q" and asset.kind == "CONSTRUCTOR"
                else 0.0
            )
            fl = (
                float(np.mean(np.isin(fastest, indices)))
                if fastest is not None
                else 0.0
            )
            mechanical, exposure = 0, 0
            for event in history[-8:]:
                for row in event["sessions"].get(kind, []):
                    same = (
                        row["tla"] == asset.tla
                        if asset.kind == "DRIVER"
                        else _team_key(row["team_name"]) == _team_key(asset.name)
                    )
                    if same and row.get("retirement_cause") not in (
                        "disqualified",
                        "did_not_start",
                    ):
                        exposure += 1
                        mechanical += row.get("retirement_cause") == "mechanical"
            result[asset.id, kind] = np.array(
                [
                    float(finish[:, indices].sum(axis=1).mean()),
                    float(gain[:, indices].sum(axis=1).mean()),
                    float((~classified[:, indices]).sum(axis=1).mean()),
                    fl,
                    both_q3,
                    any_q3,
                    (mechanical + 0.5) / (exposure + 5),
                    _recent(labels, asset.id, kind),
                ]
            )
    return result


def _predict(training, targets, config):
    half, ridge = config
    x = np.array([r["x"] for r in training])
    y = np.array([r["y"] for r in training])
    weights = np.array(
        [
            2 ** (-(max(r["event"] for r in training) - r["event"]) / half)
            for r in training
        ]
    )
    centre = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average((x - centre) ** 2, axis=0, weights=weights))
    scale = np.maximum(scale, 1.0)
    design = np.column_stack([np.ones(len(x)), (x - centre) / scale])
    penalty = np.diag([0.0] + [ridge] * x.shape[1])
    coefficients = np.linalg.solve(
        design.T @ (weights[:, None] * design) + penalty, design.T @ (weights * y)
    )
    return (
        np.column_stack([np.ones(len(targets)), (np.array(targets) - centre) / scale])
        @ coefficients
    )


def _source(assets, cutoff):
    source = public_history.current()
    if not source:
        return None
    d = source["document"]
    racing = [r for r in d.get("racing", []) if public_history.date(r["end"]) < cutoff]
    fantasy = {
        day: rows
        for day, rows in d.get("fantasy", {}).items()
        if day in d.get("fantasy_events", {})
        and public_history.date(d["fantasy_events"][day]) < cutoff
    }
    if len(fantasy) < 6 or not racing_model.timed(racing):
        return None
    return json.dumps(
        dict(
            racing=racing,
            fantasy=fantasy,
            fantasy_events={k: d["fantasy_events"][k] for k in fantasy},
            telemetry_sha256=hashlib.sha256(
                json.dumps(
                    [
                        row
                        for row in d.get("features", [])
                        if public_history.date(row["completed_at"]) < cutoff
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        ),
        sort_keys=True,
        separators=(",", ":"),
    )


@lru_cache(maxsize=2)
def _fit(source, assets, telemetry):
    from .projections import _estimate_legacy

    d = json.loads(source)
    racing = sorted(d["racing"], key=lambda r: r["end"])
    season = max(r["season"] for r in racing)
    preseason = [r for r in racing if r["season"] < season]
    if not racing_model.timed(preseason):
        return None
    # Fit racing-feature parameters before the evaluated Fantasy season, not
    # against its later results. Fantasy coefficients adapt inside that season.
    parameters = racing_model.evaluate(preseason, simulations=300)["parameters"]
    labels, folds = [], []
    errors = {
        (population, kind): []
        for population in ("DRIVER", "CONSTRUCTOR")
        for kind in ("Q", "S", "R")
    }
    for record in (r for r in racing if r["season"] == season):
        days = [
            day
            for day, end in d["fantasy_events"].items()
            if abs(
                (
                    public_history.date(end) - public_history.date(record["end"])
                ).total_seconds()
            )
            < 12 * 3600
        ]
        if len(days) != 1:
            continue
        day = days[0]
        cutoff = public_history.date(record["race_start_utc"]) - timedelta(days=3)
        history = [r for r in racing if public_history.date(r["end"]) < cutoff]
        available = {row["tla"] for row in record["sessions"]["R"]}
        target_assets = tuple(
            a for a in assets if a.kind == "CONSTRUCTOR" or a.tla in available
        )
        if len([a for a in target_assets if a.kind == "DRIVER"]) != 2 * len(
            [a for a in target_assets if a.kind == "CONSTRUCTOR"]
        ):
            continue
        weekend = Weekend(
            season,
            record["round"],
            record.get("name", "Historical race"),
            int(day),
            cutoff,
            "S" in record["sessions"],
            False,
            public_history.date(d["fantasy_events"][day]),
        )
        features = _features(
            target_assets,
            weekend,
            history,
            labels,
            parameters,
            telemetry,
            7100 + record["round"],
        )
        baseline = _estimate_legacy(target_assets, [weekend], use_telemetry=telemetry)
        outcomes = {str(row["PlayerId"]): row for row in d["fantasy"][day]}
        additions, pending = [], []
        for asset in target_assets:
            outcome = outcomes.get(asset.id)
            if outcome is None:
                continue
            for index, kind in enumerate(("Q", "S", "R")):
                if (asset.id, kind) not in features:
                    continue
                raw = outcome.get(
                    {"Q": "QualifyingPoints", "S": "SprintPoints", "R": "RacePoints"}[
                        kind
                    ]
                )
                if raw in (None, ""):
                    continue
                try:
                    y = float(raw)
                    if kind == "R":
                        if weekend.sprint and outcome.get("SprintPoints") in (None, ""):
                            continue
                        y = (
                            float(outcome["GamedayPoints"])
                            - float(outcome["QualifyingPoints"])
                            - float(outcome.get("SprintPoints") or 0)
                        )
                except (KeyError, TypeError, ValueError):
                    continue
                if not np.isfinite(y):
                    continue
                group = (asset.kind, kind)
                train = [r for r in labels if (r["kind"], r["session"]) == group]
                x = features[asset.id, kind].tolist()
                if len({r["event"] for r in train}) >= 3:
                    predictions = [float(_predict(train, [x], c)[0]) for c in CONFIGS]
                    prior_errors = errors[group]
                    chosen = (
                        min(
                            range(len(CONFIGS)),
                            key=lambda i: sum(e["errors"][i] for e in prior_errors),
                        )
                        if prior_errors
                        else 0
                    )
                    old = (
                        baseline[0, asset.id].qualifying,
                        baseline[0, asset.id].sprint,
                        baseline[0, asset.id].race,
                    )[index]
                    naive = _recent(labels, asset.id, kind)
                    folds.append(
                        dict(
                            round=record["round"],
                            cutoff=cutoff.isoformat(),
                            id=asset.id,
                            kind=asset.kind,
                            session=kind,
                            actual=y,
                            predicted=predictions[chosen],
                            legacy=old,
                            recent=naive,
                            training_rounds=sorted({r["event"] for r in train}),
                        )
                    )
                    # All participants in a weekend share earlier-only tuning;
                    # add validation errors only after the entire race is scored.
                    additions.append(
                        (group, dict(errors=[abs(p - y) for p in predictions]))
                    )
                pending.append(
                    dict(
                        id=asset.id,
                        kind=asset.kind,
                        session=kind,
                        event=record["round"],
                        x=x,
                        y=y,
                    )
                )
        labels.extend(pending)
        for group, error in additions:
            errors[group].append(error)
    groups = {}
    for group, validations in errors.items():
        rows = [r for r in folds if (r["kind"], r["session"]) == group]
        metrics = (
            {
                key: float(np.mean([abs(r[key] - r["actual"]) for r in rows]))
                for key in ("predicted", "legacy", "recent")
            }
            if rows
            else {}
        )
        ready = len({r["round"] for r in rows}) >= 5 and metrics["predicted"] < min(
            metrics["legacy"], metrics["recent"]
        )
        choice = (
            min(
                range(len(CONFIGS)),
                key=lambda i: sum(e["errors"][i] for e in validations),
            )
            if validations
            else 0
        )
        groups["/".join(group)] = dict(
            selected=ready,
            parameters=CONFIGS[choice],
            evaluated_rounds=len({r["round"] for r in rows}),
            observations=len(rows),
            mae=metrics,
        )
    return dict(
        model=VERSION,
        season=season,
        calibrated=False,
        parameters=parameters,
        groups=groups,
        folds=folds,
        labels=labels,
        roster_scope="Currently identified entrants; historical Fantasy prices never enter features",
    )


def report(assets, cutoff, *, telemetry=True):
    source = _source(assets, cutoff)
    fitted = _fit(source, assets, telemetry) if source else None
    return (
        {k: v for k, v in fitted.items() if k not in ("labels",)}
        if fitted
        else dict(model=VERSION, status="insufficient_history")
    )


def forecast(assets, weekends, baseline, *, telemetry=True):
    from .projections import Estimate

    cutoff = min(weekends[0].first_session, datetime.now(timezone.utc))
    source = _source(assets, cutoff)
    fitted = _fit(source, assets, telemetry) if source else None
    if not fitted:
        return baseline
    history = json.loads(source)["racing"]
    output = dict(baseline)
    for index, weekend in enumerate(weekends):
        features = _features(
            assets,
            replace(weekend, first_session=cutoff),
            history,
            fitted["labels"],
            fitted["parameters"],
            telemetry,
            8500 + weekend.round,
        )
        for asset in assets:
            prior = baseline[index, asset.id]
            scores = [prior.qualifying, prior.sprint, prior.race]
            for position, kind in enumerate(("Q", "S", "R")):
                group = fitted["groups"][f"{asset.kind}/{kind}"]
                if not group["selected"] or (asset.id, kind) not in features:
                    continue
                train = [
                    r
                    for r in fitted["labels"]
                    if r["kind"] == asset.kind and r["session"] == kind
                ]
                scores[position] = float(
                    _predict(train, [features[asset.id, kind]], group["parameters"])[0]
                )
            output[index, asset.id] = Estimate(*scores)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument(
        "--output", type=Path, default=Path("data/fantasy-evaluation.json")
    )
    args = parser.parse_args(argv)
    from .data import snapshot

    with public_history.repository(args.history):
        live, weekends = snapshot(datetime.now(timezone.utc).year)
        result = report(
            live.assets, min(datetime.now(timezone.utc), weekends[0].first_session)
        )
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "folds"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
