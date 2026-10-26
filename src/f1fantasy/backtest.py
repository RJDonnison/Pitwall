"""Rolling pre-weekend forecast evaluation against official Fantasy results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .data import DataError, Weekend, completed_scores, load_assets, season_weekends
from .projections import estimate_assets


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


def run_backtest(
    season: int,
    count: int = 4,
    lookback: int = 5,
    now: datetime | None = None,
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
        forecasts = estimate_assets(assets, [target], lookback=lookback)
        actual = completed_scores(target.gameday_id, target.sprint)
        by_kind = {"DRIVER": [], "CONSTRUCTOR": []}
        qualifying, sprint, race = [], [], []
        for asset in assets:
            if asset.id not in actual:
                raise DataError(
                    f"Missing official outcome for {asset.name} at {target.name}"
                )
            expected = forecasts[0, asset.id]
            q, s, r = actual[asset.id]
            by_kind[asset.kind].append(abs(expected.total - (q + s + r)))
            qualifying.append(abs(expected.qualifying - q))
            if target.sprint:
                sprint.append(abs(expected.sprint - s))
            race.append(abs(expected.race - r))
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
            )
        )
    return rows
