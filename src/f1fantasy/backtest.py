"""Rolling pre-weekend forecast evaluation against official Fantasy results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .data import DataError, Weekend, completed_scores, load_assets, season_weekends
from .evaluation import selection_metrics
from .optimizer import optimize
from .price_history import DEFAULT_PRICE_DIR, load_verified
from .projections import Estimate, estimate_assets


@dataclass(frozen=True)
class BacktestAsset:
    id: str
    name: str
    kind: str
    predicted: Estimate
    actual: Estimate
    baseline_race_points: float | None = None
    features: dict[str, dict[str, float]] | None = None

    @property
    def error(self) -> float:
        return self.predicted.total - self.actual.total


@dataclass(frozen=True)
class BacktestRow:
    weekend: Weekend
    drivers: int
    constructors: int
    driver_error: float
    constructor_error: float
    qualifying_error: float
    sprint_error: float | None
    race_error: float
    assets: tuple[BacktestAsset, ...] = ()
    qualifying_bias: float = 0.0
    sprint_bias: float | None = None
    race_bias: float = 0.0
    driver_race_error: float = 0.0
    constructor_race_error: float = 0.0
    baseline_driver_race_error: float | None = None
    model_driver_race_error_on_baseline: float | None = None
    baseline_driver_count: int = 0
    selection: dict | None = None


def run_backtest(
    season: int,
    count: int = 4,
    lookback: int = 5,
    now: datetime | None = None,
    use_telemetry: bool = True,
    use_risk: bool = True,
    use_model: bool = True,
    capture_features: bool = False,
    price_dir=None,
) -> list[BacktestRow]:
    """Replay completed weekends; inputs for each forecast end before its start.

    Historical roster identities are read from the target event's archive solely
    to match predicted assets to their outcomes. Archived prices and scores of
    that event are never passed into the forecasting function.
    """
    if count < 1 or lookback < 1:
        raise ValueError("Count and lookback must be positive")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DataError("Current time must have a timezone")
    completed = [
        w
        for w in season_weekends(season)
        if w.last_session is not None and w.last_session + timedelta(days=1) < now
    ]
    if not completed:
        raise DataError("No finalized race weekends available for backtesting")
    rows = []
    for target in completed[-count:]:
        assets, _ = load_assets(target.gameday_id, require_recent=False)
        estimates = estimate_assets(
            assets,
            [target],
            lookback=lookback,
            use_telemetry=use_telemetry,
            use_risk=use_risk,
            use_model=use_model,
            return_features=capture_features,
        )
        forecasts, features = estimates if capture_features else (estimates, {})
        actual = completed_scores(target.gameday_id, target.sprint)
        by_kind = {"DRIVER": [], "CONSTRUCTOR": []}
        qualifying, sprint, race = [], [], []
        q_bias, s_bias, r_bias = [], [], []
        driver_race, constructor_race = [], []
        baseline_driver, model_driver_on_baseline = [], []
        details: list[BacktestAsset] = []
        earlier = [w for w in completed if w.last_session < target.first_session]
        recent_scores = [completed_scores(w.gameday_id, w.sprint) for w in earlier[-3:]]
        for asset in assets:
            if asset.id not in actual:
                raise DataError(
                    f"Missing official outcome for {asset.name} at {target.name}"
                )
            expected = forecasts[0, asset.id]
            q, s, r = actual[asset.id]
            older = [week[asset.id][2] for week in recent_scores if asset.id in week]
            naive_race = sum(older) / len(older) if older else None
            details.append(
                BacktestAsset(
                    asset.id,
                    asset.name,
                    asset.kind,
                    expected,
                    Estimate(q, s, r),
                    naive_race,
                    features.get((0, asset.id)),
                )
            )
            by_kind[asset.kind].append(abs(expected.total - (q + s + r)))
            qualifying.append(abs(expected.qualifying - q))
            q_bias.append(expected.qualifying - q)
            if target.sprint:
                sprint.append(abs(expected.sprint - s))
                s_bias.append(expected.sprint - s)
            race.append(abs(expected.race - r))
            r_bias.append(expected.race - r)
            if asset.kind == "DRIVER":
                driver_race.append(abs(expected.race - r))
                if naive_race is not None:
                    baseline_driver.append(abs(naive_race - r))
                    model_driver_on_baseline.append(abs(expected.race - r))
            else:
                constructor_race.append(abs(expected.race - r))
        selection = selection_metrics(tuple(details))
        archived = load_verified(target, price_dir or DEFAULT_PRICE_DIR)
        if archived is not None:
            if all(a.id in actual and (0, a.id) in forecasts for a in archived):
                predicted_team = optimize(archived, [target], forecasts, 1000)[0]
                actual_estimates = {
                    (0, a.id): Estimate(*actual[a.id]) for a in archived
                }
                best = optimize(archived, [target], actual_estimates, 1000)[0]
                selected = predicted_team.drivers + predicted_team.constructors
                realized = (
                    sum(actual_estimates[0, a.id].total for a in selected)
                    + actual_estimates[0, predicted_team.boost.id].total
                )
                selection["budgeted_initial_team"] = {
                    "budget_tenths_m": 1000,
                    "picked_actual_points": realized,
                    "hindsight_best_points": best.expected_points,
                    "regret_points": max(0.0, best.expected_points - realized),
                    "selected_ids": [a.id for a in selected],
                    "boost_driver_id": predicted_team.boost.id,
                }
            else:
                selection["budgeted_initial_team"] = None
                selection["budgeted_unavailable_reason"] = (
                    "Archived roster lacks some official outcomes"
                )
        else:
            selection["budgeted_initial_team"] = None
            selection["budgeted_unavailable_reason"] = (
                "No verified pre-lock Fantasy price snapshot"
            )
        rows.append(
            BacktestRow(
                target,
                len(by_kind["DRIVER"]),
                len(by_kind["CONSTRUCTOR"]),
                sum(by_kind["DRIVER"]) / len(by_kind["DRIVER"]),
                sum(by_kind["CONSTRUCTOR"]) / len(by_kind["CONSTRUCTOR"]),
                sum(qualifying) / len(qualifying),
                sum(sprint) / len(sprint) if sprint else None,
                sum(race) / len(race),
                tuple(details),
                sum(q_bias) / len(q_bias),
                sum(s_bias) / len(s_bias) if s_bias else None,
                sum(r_bias) / len(r_bias),
                sum(driver_race) / len(driver_race),
                sum(constructor_race) / len(constructor_race),
                sum(baseline_driver) / len(baseline_driver)
                if baseline_driver
                else None,
                (
                    sum(model_driver_on_baseline) / len(model_driver_on_baseline)
                    if model_driver_on_baseline
                    else None
                ),
                len(baseline_driver),
                selection,
            )
        )
    return rows
