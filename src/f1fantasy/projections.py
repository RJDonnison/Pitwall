"""Conservative, pre-weekend Fantasy point estimates from FastF1 results.

FastF1 does not expose official Fantasy overtakes, Driver of the Day or pit-stop
bonuses consistently. These estimates intentionally exclude those categories.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import fastf1

from .data import Asset, DataError, Weekend, fastf1_weekend

QUALIFYING = {position: 11 - position for position in range(1, 11)}
RACE = {
    position: points
    for position, points in enumerate((25, 18, 15, 12, 10, 8, 6, 4, 2, 1), start=1)
}
SPRINT = {position: 9 - position for position in range(1, 9)}


@dataclass(frozen=True)
class Estimate:
    qualifying: float
    sprint: float
    race: float

    @property
    def total(self) -> float:
        return self.qualifying + self.sprint + self.race


def _position(value: Any) -> int | None:
    try:
        number = float(value)
        if isfinite(number) and number > 0 and number.is_integer():
            return int(number)
    except (TypeError, ValueError):
        pass
    return None


def _session_scores(year: int, round_number: int, kind: str) -> dict[str, float]:
    try:
        session = fastf1.get_session(year, round_number, kind)
        session.load(laps=False, telemetry=False, weather=False, messages=False)
        results = session.results
        if results is None or results.empty:
            raise DataError(f"Empty FastF1 {kind} results for round {round_number}")
        scores = {}
        for _, row in results.iterrows():
            tla = str(row["Abbreviation"])
            position = _position(row["Position"])
            if kind == "Q":
                score = QUALIFYING.get(position, 0) if position else -5
            else:
                finish = RACE if kind == "R" else SPRINT
                score = (
                    finish.get(position, 0)
                    if position
                    else (-20 if kind == "R" else -10)
                )
                grid = _position(row.get("GridPosition"))
                if grid and position:
                    change = grid - position
                    score += max(-10, change) if kind == "S" else change
            scores[tla] = float(score)
        return scores
    except DataError:
        raise
    except Exception as exc:
        raise DataError(
            f"Could not load completed FastF1 {kind} results for round {round_number}: {exc}"
        ) from exc


def estimate_assets(
    assets: tuple[Asset, ...], weekends: list[Weekend], lookback: int = 5
) -> dict[tuple[int, str], Estimate]:
    """Use completed rounds strictly before the first predicted weekend.

    Upcoming events share the same historical inputs; Sprint forecasts differ by
    event format. Future prices and future results are never used as evidence.
    """
    if not weekends or lookback < 1:
        raise ValueError("Need upcoming weekends and at least one historical race")
    for weekend in weekends:
        fastf1_weekend(weekend)
    first = weekends[0]
    prior = list(range(max(1, first.round - lookback), first.round))
    if not prior:
        raise DataError("No completed current-season race to train on")
    history: dict[str, dict[str, list[float]]] = {}
    for round_number in prior:
        event = fastf1.get_event(first.season, round_number)
        # A postponed or delayed event must never leak into a prediction.
        if (
            event.get_session_date("Race", utc=True)
            .to_pydatetime()
            .replace(tzinfo=first.first_session.tzinfo)
            >= first.first_session
        ):
            continue
        for kind in ("Q", "R", "S"):
            if kind == "S" and "sprint" not in str(event["EventFormat"]).lower():
                continue
            for tla, score in _session_scores(first.season, round_number, kind).items():
                history.setdefault(tla, {}).setdefault(kind, []).append(score)
    if not any(h.get("R") for h in history.values()):
        raise DataError("No completed race results available before the weekend")

    def mean(tla: str, kind: str, default: float) -> float:
        values = history.get(tla, {}).get(kind, [])
        if not values:
            return default
        weights = list(range(1, len(values) + 1))
        return sum(v * w for v, w in zip(values, weights)) / sum(weights)

    drivers = [a for a in assets if a.kind == "DRIVER"]
    output: dict[tuple[int, str], Estimate] = {}
    for index, weekend in enumerate(weekends):
        for driver in drivers:
            q = mean(driver.tla, "Q", 0)
            r = mean(driver.tla, "R", 0)
            # Sprint races have fewer laps/points. A previous Sprint is preferred
            # over a scaled race estimate, without inventing Sprint qualifying points.
            s = mean(driver.tla, "S", r * 0.35) if weekend.sprint else 0.0
            output[index, driver.id] = Estimate(q, s, r)
        for constructor in (a for a in assets if a.kind == "CONSTRUCTOR"):
            members = [
                output[index, d.id] for d in drivers if d.team_id == constructor.team_id
            ]
            if len(members) != 2:
                raise DataError(f"Expected two active drivers for {constructor.name}")
            q = sum(m.qualifying for m in members)
            # Constructor qualifying advancement is based on both drivers' form.
            bonus = (
                10
                if all(m.qualifying >= 1 for m in members)
                else 3
                if any(m.qualifying >= 1 for m in members)
                else -1
            )
            output[index, constructor.id] = Estimate(
                q + bonus, sum(m.sprint for m in members), sum(m.race for m in members)
            )
    return output
