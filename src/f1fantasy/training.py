"""Chronological, small-sample calibration of existing pre-weekend forecasts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

from .backtest import BacktestRow, run_backtest
from .component_training import replay as component_replay
from .data import DataError, season_weekends
from .feature_training import from_backtests, prior_features, replay as feature_replay
from .prior_history import PriorWeek, load_previous_season
from .risk import expected_session_points

MODEL_VERSION = 5
DEFAULT_MODEL_DIR = Path(".f1fantasy/models")


@dataclass(frozen=True)
class Observation:
    round: int
    kind: str
    session: str
    actual: float
    signals: tuple[float, ...]
    source: str = "current_official"


def _source_weight(source: str) -> float:
    return {"fastf1_proxy": 0.2, "imported_official": 0.65, "current_official": 1.0}[
        source
    ]


def model_path(season: int, directory: Path = DEFAULT_MODEL_DIR) -> Path:
    return directory / f"{season}-calibration-v{MODEL_VERSION}.json"


def observations(
    risk_rows: list[BacktestRow], legacy_rows: list[BacktestRow]
) -> list[Observation]:
    """Align forecasts whose feature cutoffs precede the same target weekend."""
    if [r.weekend.round for r in risk_rows] != [r.weekend.round for r in legacy_rows]:
        raise DataError("Training forecast weekends are not aligned")
    output = []
    for newer, older in zip(risk_rows, legacy_rows):
        by_id = {asset.id: asset for asset in older.assets}
        for asset in newer.assets:
            before = by_id.get(asset.id)
            if (
                before is None
                or before.kind != asset.kind
                or before.actual != asset.actual
            ):
                raise DataError(f"Training forecast asset mismatch: {asset.name}")
            for session in (
                ("qualifying", "sprint", "race")
                if newer.weekend.sprint
                else ("qualifying", "race")
            ):
                target = getattr(asset.actual, session)
                modern = getattr(asset.predicted, session)
                old = getattr(before.predicted, session)
                signals = (
                    (
                        modern,
                        old,
                        asset.baseline_race_points
                        if asset.baseline_race_points is not None
                        else modern,
                    )
                    if session == "race"
                    else (modern, old)
                )
                if not all(isfinite(value) for value in (target, *signals)):
                    raise DataError(f"Invalid training score for {asset.name}")
                output.append(
                    Observation(
                        newer.weekend.round, asset.kind, session, target, signals
                    )
                )
    return output


def chronological_split(rounds: list[int]) -> tuple[list[int], list[int], list[int]]:
    unique = sorted(set(rounds))
    if len(unique) < 8:
        raise DataError("Need at least eight completed scoring weekends for training")
    train_end = ceil(len(unique) / 2)
    val_end = train_end + max(2, (len(unique) - train_end) // 2)
    if len(unique) - val_end < 2:
        raise DataError("Need at least two untouched test weekends")
    return unique[:train_end], unique[train_end:val_end], unique[val_end:]


def _fit(samples: list[Observation], count: int) -> list[float]:
    """Minimize absolute error with nonnegative weights and a baseline prior."""
    n = len(samples)
    sources = [_source_weight(sample.source) for sample in samples]
    objective = np.array(
        [-0.3] + [0.0] * (count - 1) + [weight / sum(sources) for weight in sources]
    )
    constraints, limits = [], []
    for index, sample in enumerate(samples):
        positive = list(sample.signals) + [0.0] * n
        positive[count + index] = -1
        negative = [-value for value in sample.signals] + [0.0] * n
        negative[count + index] = -1
        constraints.extend((positive, negative))
        limits.extend((sample.actual, -sample.actual))
    result = linprog(
        objective,
        A_ub=constraints,
        b_ub=limits,
        A_eq=[[1.0] * count + [0.0] * n],
        b_eq=[1.0],
        bounds=[(0, 1)] * count + [(0, None)] * n,
        method="highs",
    )
    if not result.success or result.x is None:
        raise DataError(f"Cannot fit model weights: {result.message}")
    return [float(weight) for weight in result.x[:count]]


def _mae(rows: list[Observation], weights: list[float]) -> float:
    return sum(
        abs(sum(w * signal for w, signal in zip(weights, item.signals)) - item.actual)
        for item in rows
    ) / len(rows)


def fit_calibration(items: list[Observation], season: int) -> dict:
    train, validation, test = chronological_split([item.round for item in items])
    report: dict = {
        "version": MODEL_VERSION,
        "season": season,
        "trained_rounds": train,
        "validation_rounds": validation,
        "test_rounds": test,
        "last_completed_round": test[-1],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights": {},
        "metrics": {},
        "active": False,
    }
    for kind in ("DRIVER", "CONSTRUCTOR"):
        report["weights"][kind] = {}
        report["metrics"][kind] = {}
        for session in ("qualifying", "sprint", "race"):
            selected = [
                item for item in items if item.kind == kind and item.session == session
            ]
            dimensions = 3 if session == "race" else 2
            default = [1.0] + [0.0] * (dimensions - 1)
            a = [item for item in selected if item.round in train]
            b = [item for item in selected if item.round in validation]
            c = [item for item in selected if item.round in test]
            # One or two Sprints are insufficient to learn a separate model.
            if (
                len({i.round for i in a}) < 3
                or len({i.round for i in b}) < 2
                or len({i.round for i in c}) < 2
            ):
                report["weights"][kind][session] = default
                report["metrics"][kind][session] = {
                    "reason": "insufficient weekends",
                    "promoted": False,
                    "samples": [len(a), len(b), len(c)],
                }
                continue
            candidate = _fit(a, dimensions)
            baseline_validation = _mae(b, default)
            candidate_validation = _mae(b, candidate)
            baseline_test = _mae(c, default)
            candidate_test = _mae(c, candidate)
            promote = (
                candidate_validation + 0.05 < baseline_validation
                and candidate_test + 0.05 < baseline_test
            )
            report["weights"][kind][session] = candidate if promote else default
            report["metrics"][kind][session] = {
                "candidate_weights": candidate,
                "promoted": promote,
                "samples": [len(a), len(b), len(c)],
                "validation": {
                    "baseline_mae": baseline_validation,
                    "candidate_mae": candidate_validation,
                },
                "test": {
                    "baseline_mae": baseline_test,
                    "candidate_mae": candidate_test,
                },
            }
            report["active"] |= promote
    return report


def prior_observations(
    weeks: list[PriorWeek], source: str = "fastf1_proxy"
) -> list[Observation]:
    """Generate warm-start examples; never use a weekend as its own feature."""
    output: list[Observation] = []
    history: dict[str, dict[str, list[float]]] = {}
    for week in weeks:
        drivers = [asset for asset in week.assets if asset.kind == "DRIVER"]
        for asset in week.assets:
            past = history.get(asset.id, {})
            if len(past.get("R", [])) < 3:
                continue
            race = past["R"]
            legacy_race = sum(
                value * index for index, value in enumerate(race, 1)
            ) / sum(range(1, len(race) + 1))
            naive_race = sum(race[-3:]) / 3
            risk_race = (
                expected_session_points(asset, "R", history, drivers, legacy_race)
                if asset.kind == "DRIVER"
                else legacy_race
            )
            old_q = past.get("Q", [])
            q_forecast = sum(old_q[-3:]) / len(old_q[-3:]) if old_q else 0.0
            actual = week.scores[asset.id]
            output.append(
                Observation(
                    week.weekend.round,
                    asset.kind,
                    "qualifying",
                    actual.qualifying,
                    (q_forecast, q_forecast),
                    source,
                )
            )
            output.append(
                Observation(
                    week.weekend.round,
                    asset.kind,
                    "race",
                    actual.race,
                    (risk_race, legacy_race, naive_race),
                    source,
                )
            )
            if week.weekend.sprint:
                sprint_history = past.get("S", [])
                legacy_sprint = (
                    sum(sprint_history) / len(sprint_history)
                    if sprint_history
                    else max(0, legacy_race) * 0.35
                )
                risk_sprint = (
                    expected_session_points(
                        asset,
                        "S",
                        history,
                        drivers,
                        legacy_sprint,
                        race_finish_reference=risk_race,
                    )
                    if asset.kind == "DRIVER"
                    else legacy_sprint
                )
                output.append(
                    Observation(
                        week.weekend.round,
                        asset.kind,
                        "sprint",
                        actual.sprint,
                        (risk_sprint, legacy_sprint),
                        source,
                    )
                )
        for asset in week.assets:
            points = week.scores[asset.id]
            record = history.setdefault(asset.id, {})
            for phase, value in (
                ("Q", points.qualifying),
                ("S", points.sprint),
                ("R", points.race),
            ):
                if phase != "S" or week.weekend.sprint:
                    record.setdefault(phase, []).append(value)
    if len({item.round for item in output}) < 5:
        raise DataError("Previous season lacks enough completed race examples")
    return output


def replay_calibration(
    prior: list[Observation], current: list[Observation], season: int, source: str
) -> dict:
    """Test current-season round N, then add N to training before round N+1."""
    if len({item.round for item in prior}) < 5:
        raise DataError("Need at least five previous-season warm-start races")
    rounds = sorted({item.round for item in current})
    pool = list(prior)
    weekly = []
    recorded: dict[tuple[str, str], list[tuple[int, float, float]]] = {}
    for round_number in rounds:
        target = [item for item in current if item.round == round_number]
        errors: dict[str, dict] = {}
        for kind in ("DRIVER", "CONSTRUCTOR"):
            for phase in ("qualifying", "sprint", "race"):
                sample = [
                    item
                    for item in target
                    if item.kind == kind and item.session == phase
                ]
                if not sample:
                    continue
                historical = [
                    item for item in pool if item.kind == kind and item.session == phase
                ]
                count = len(sample[0].signals)
                base = [1.0] + [0.0] * (count - 1)
                distinct = len({item.round for item in historical})
                # A few prior Sprints cannot justify independent tuning.
                weights = (
                    _fit(historical, count)
                    if distinct >= (3 if phase == "sprint" else 5)
                    else base
                )
                old_error, new_error = _mae(sample, base), _mae(sample, weights)
                recorded.setdefault((kind, phase), []).append(
                    (round_number, old_error, new_error)
                )
                errors[f"{kind}.{phase}"] = {
                    "baseline_mae": old_error,
                    "replay_mae": new_error,
                    "weights_before_race": weights,
                    "prior_examples": len(historical),
                }
        weekly.append({"round": round_number, "errors": errors})
        pool.extend(target)  # never let the tested round leak into its own fit
    report: dict = {
        "version": MODEL_VERSION,
        "mode": "prequential",
        "season": season,
        "prior_season": season - 1,
        "prior_source": source,
        "prior_examples": len(prior),
        "prior_example_weight": _source_weight(source),
        "replay_rounds": rounds,
        "weekly": weekly,
        "last_completed_round": rounds[-1] if rounds else 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights": {},
        "metrics": {},
        "active": False,
    }
    for kind in ("DRIVER", "CONSTRUCTOR"):
        report["weights"][kind], report["metrics"][kind] = {}, {}
        for phase in ("qualifying", "sprint", "race"):
            observations_for_phase = [
                item for item in pool if item.kind == kind and item.session == phase
            ]
            count = 3 if phase == "race" else 2
            base = [1.0] + [0.0] * (count - 1)
            comparisons = recorded.get((kind, phase), [])
            if len(comparisons) < (3 if phase == "sprint" else 5):
                report["weights"][kind][phase] = base
                report["metrics"][kind][phase] = {
                    "reason": "insufficient replay races",
                    "promoted": False,
                }
                continue
            baseline = sum(item[1] for item in comparisons) / len(comparisons)
            replay = sum(item[2] for item in comparisons) / len(comparisons)
            recent = comparisons[len(comparisons) // 2 :]
            baseline_recent = sum(item[1] for item in recent) / len(recent)
            replay_recent = sum(item[2] for item in recent) / len(recent)
            promoted = (
                replay + 0.05 < baseline and replay_recent + 0.05 < baseline_recent
            )
            report["weights"][kind][phase] = (
                _fit(observations_for_phase, count) if promoted else base
            )
            report["metrics"][kind][phase] = {
                "promoted": promoted,
                "weekends": len(comparisons),
                "baseline_mae": baseline,
                "replay_mae": replay,
                "recent_baseline_mae": baseline_recent,
                "recent_replay_mae": replay_recent,
            }
            report["active"] |= promoted
    return report


def load_model(season: int, directory: Path = DEFAULT_MODEL_DIR) -> dict | None:
    path = model_path(season, directory)
    if not path.exists():
        return None
    try:
        result = json.loads(path.read_text())
        if (
            result["version"] != MODEL_VERSION
            or result["season"] != season
            or not isinstance(result["active"], bool)
            or not isinstance(result["last_completed_round"], int)
        ):
            raise DataError("Invalid saved calibration metadata")
        for kind in ("DRIVER", "CONSTRUCTOR"):
            for session, size in (("qualifying", 2), ("sprint", 2), ("race", 3)):
                weights = result["weights"][kind][session]
                if (
                    len(weights) != size
                    or any(not isfinite(float(w)) or float(w) < 0 for w in weights)
                    or abs(sum(weights) - 1) > 1e-6
                ):
                    raise DataError("Invalid saved calibration weights")
        if result.get("feature_names") is not None:
            from .feature_training import FEATURE_NAMES

            if tuple(result["feature_names"]) != FEATURE_NAMES:
                raise DataError("Invalid saved feature model schema")
            for kind in ("DRIVER", "CONSTRUCTOR"):
                for phase in ("qualifying", "sprint", "race"):
                    vector = result["feature_weights"][kind][phase]
                    if len(vector) != len(FEATURE_NAMES) or any(
                        not isfinite(float(value)) or abs(float(value)) > 8
                        for value in vector
                    ):
                        raise DataError("Invalid saved feature weights")
        if result.get("component_weights") is not None:
            weights = result["component_weights"]
            if (
                not 0.5 <= float(weights["probability_scale"]) <= 2.0
                or not -5 <= float(weights["classified_bias"]) <= 5
            ):
                raise DataError("Invalid saved reliability weights")
        return result
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise DataError(f"Cannot verify saved model {path}: {exc}") from exc


def train(
    season: int,
    *,
    directory: Path = DEFAULT_MODEL_DIR,
    lookback: int = 5,
    now: datetime | None = None,
    prior_scores_file: Path | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    complete = [
        w
        for w in season_weekends(season)
        if w.last_session is not None and w.last_session + timedelta(days=1) < now
    ]
    previous = load_model(season, directory)
    desired_source = "imported_official" if prior_scores_file else "fastf1_proxy"
    last_round = complete[-1].round if complete else 0
    if (
        previous is not None
        and previous["last_completed_round"] >= last_round
        and previous.get("prior_source") == desired_source
    ):
        if previous.get("lookback", 5) != lookback:
            raise DataError(
                "A model for these completed races already uses a different lookback; wait for another finalized race before retuning"
            )
        return previous
    prior_weeks, source = load_previous_season(season, official_file=prior_scores_file)
    warm_start = prior_observations(prior_weeks, source)
    current = (
        run_backtest(
            season,
            count=len(complete),
            lookback=lookback,
            now=now,
            use_risk=True,
            use_model=False,
            capture_features=True,
        )
        if complete
        else []
    )
    legacy = (
        run_backtest(
            season,
            count=len(complete),
            lookback=lookback,
            now=now,
            use_risk=False,
            use_model=False,
        )
        if complete
        else []
    )
    report = replay_calibration(
        warm_start, observations(current, legacy), season, source
    )
    previous_features, current_features = (
        prior_features(warm_start),
        from_backtests(current),
    )
    report.update(feature_replay(previous_features, current_features))
    report.update(component_replay(previous_features, current_features))
    if (
        report["component_active"]
        and report["feature_metrics"]["DRIVER"]["race"]["promoted"]
    ):
        if (
            report["feature_metrics"]["DRIVER"]["race"]["feature_mae"]
            < report["component_metrics"]["component_race_mae"]
        ):
            report["component_active"] = False
            report["component_metrics"]["promoted"] = False
        else:
            report["feature_metrics"]["DRIVER"]["race"]["promoted"] = False
            report["feature_weights"]["DRIVER"]["race"] = [0.0] * len(
                report["feature_names"]
            )
            report["feature_active"] = any(
                metrics["promoted"]
                for kinds in report["feature_metrics"].values()
                for metrics in kinds.values()
            )
    report["active"] |= report["feature_active"] or report["component_active"]
    report["lookback"] = lookback
    path = model_path(season, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, allow_nan=False, indent=2) + "\n")
    temporary.replace(path)
    return report
