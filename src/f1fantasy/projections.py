"""Pre-weekend predictions from completed Fantasy scores and FastF1 form."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any
import unicodedata

import fastf1

from .data import (
    Asset,
    DataError,
    Weekend,
    completed_scores,
    fastf1_weekend,
    season_weekends,
)
from .history import configure_cache
from .telemetry_model import adjustments as telemetry_adjustments

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
                classified = _position(row.get("ClassifiedPosition"))
                score = (
                    finish.get(position, 0)
                    if classified
                    else (-20 if kind == "R" else -10)
                )
                grid = _position(row.get("GridPosition"))
                if grid and classified and position:
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


def _venue(value: object) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(value)).lower() if c.isalnum()
    )


def _track_form(
    weekends: list[Weekend],
    cutoff: Any,
) -> dict[int, dict[str, dict[str, list[tuple[int, float]]]]]:
    """Earlier visits to each upcoming venue, independent of season form."""
    locations = {
        index: _venue(fastf1.get_event(w.season, w.round)["Location"])
        for index, w in enumerate(weekends)
    }
    track: dict[int, dict[str, dict[str, list[tuple[int, float]]]]] = {
        index: {} for index in locations
    }
    for year in range(weekends[0].season - 2, weekends[0].season + 1):
        schedule = fastf1.get_event_schedule(year)
        for _, row in schedule.iterrows():
            round_number = int(row["RoundNumber"])
            if round_number < 1:
                continue
            matched = [
                index
                for index, location in locations.items()
                if location and _venue(row["Location"]) == location
            ]
            if not matched:
                continue
            event = fastf1.get_event(year, round_number)
            race_date = event.get_session_date("Race", utc=True).to_pydatetime()
            if race_date.replace(tzinfo=cutoff.tzinfo) >= cutoff:
                continue
            for kind in ("Q", "R", "S"):
                if kind == "S" and "sprint" not in str(event["EventFormat"]).lower():
                    continue
                results = _session_scores(year, round_number, kind)
                for index in matched:
                    for tla, score in results.items():
                        track[index].setdefault(tla, {}).setdefault(kind, []).append(
                            (year, score)
                        )
    return track


def estimate_assets(
    assets: tuple[Asset, ...],
    weekends: list[Weekend],
    lookback: int = 5,
    *,
    use_telemetry: bool = True,
) -> dict[tuple[int, str], Estimate]:
    """Use completed rounds strictly before the first predicted weekend.

    Upcoming events share the same historical inputs; Sprint forecasts differ by
    event format. Future prices and future results are never used as evidence.
    """
    if not weekends or lookback < 1:
        raise ValueError("Need upcoming weekends and at least one historical race")
    configure_cache()
    for weekend in weekends:
        fastf1_weekend(weekend)
    first = weekends[0]
    prior = [
        (first.season, r) for r in range(max(1, first.round - lookback), first.round)
    ]
    if len(prior) < lookback:
        try:
            schedule = fastf1.get_event_schedule(first.season - 1)
            rounds = sorted(int(n) for n in schedule["RoundNumber"] if int(n) > 0)
            prior = [
                (first.season - 1, r) for r in rounds[-(lookback - len(prior)) :]
            ] + prior
        except Exception as exc:
            if not prior:
                raise DataError(f"Cannot load prior-season history: {exc}") from exc
    history: dict[str, dict[str, list[tuple[int, float]]]] = {}
    fantasy_history: dict[str, dict[str, list[float]]] = {}
    completed = {
        w.round: w
        for w in season_weekends(first.season)
        if w.last_session is not None and w.last_session < first.first_session
    }
    for year, round_number in prior:
        event = fastf1.get_event(year, round_number)
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
            for tla, score in _session_scores(year, round_number, kind).items():
                history.setdefault(tla, {}).setdefault(kind, []).append((year, score))
        if year == first.season and round_number in completed:
            historic = completed[round_number]
            for id_, (q, s, r) in completed_scores(
                historic.gameday_id, historic.sprint
            ).items():
                record = fantasy_history.setdefault(id_, {})
                for kind, points in (("Q", q), ("R", r)):
                    record.setdefault(kind, []).append(points)
                if historic.sprint:
                    record.setdefault("S", []).append(s)
    if not any(h.get("R") for h in history.values()):
        raise DataError("No completed race results available before the weekend")
    track = _track_form(weekends, first.first_session)
    telemetry = telemetry_adjustments(assets, weekends) if use_telemetry else {}

    def mean(values: list[float], default: float) -> float:
        if not values:
            return default
        weights = list(range(1, len(values) + 1))
        return sum(v * w for v, w in zip(values, weights)) / sum(weights)

    def season_mean(values: list[tuple[int, float]], default: float) -> float:
        if not values:
            return default
        weights = [
            (index + 1)
            * (
                4.0
                if year == first.season
                else 1.0
                if year == first.season - 1
                else 0.5
            )
            for index, (year, _) in enumerate(values)
        ]
        return sum(score * weight for (_, score), weight in zip(values, weights)) / sum(
            weights
        )

    def blended(id_: str, kind: str, fallback: float) -> float:
        values = fantasy_history.get(id_, {}).get(kind, [])
        if not values:
            return fallback
        # Official Fantasy history contains overtakes, fastest laps, DOTD,
        # qualifying advancement and pit-stop bonuses absent from FastF1
        # classifications. FastF1 form limits noise from very small samples.
        share = min(0.85, 0.5 + 0.1 * len(values))
        return share * mean(values, fallback) + (1 - share) * fallback

    def track_adjusted(
        index: int, tla: str, kind: str, baseline: float, predicted: float
    ) -> float:
        visits = track[index].get(tla, {}).get(kind, [])
        if not visits:
            return predicted
        weight = min(0.30, 0.10 + 0.08 * len(visits))
        if not any(year == first.season for year, _ in visits):
            weight = min(weight, 0.15)
        return predicted + weight * (season_mean(visits, baseline) - baseline)

    drivers = [a for a in assets if a.kind == "DRIVER"]
    output: dict[tuple[int, str], Estimate] = {}
    for index, weekend in enumerate(weekends):
        for driver in drivers:
            base = history.get(driver.tla, {})
            q_base = season_mean(base.get("Q", []), 0)
            r_base = season_mean(base.get("R", []), 0)
            q = track_adjusted(
                index, driver.tla, "Q", q_base, blended(driver.id, "Q", q_base)
            )
            r = track_adjusted(
                index, driver.tla, "R", r_base, blended(driver.id, "R", r_base)
            )
            s_base = season_mean(base.get("S", []), r * 0.35)
            s = (
                track_adjusted(
                    index, driver.tla, "S", s_base, blended(driver.id, "S", s_base)
                )
                if weekend.sprint
                else 0.0
            )
            q_delta, s_delta, r_delta = telemetry.get(
                (index, driver.id), (0.0, 0.0, 0.0)
            )
            q, s, r = q + q_delta, s + s_delta, r + r_delta
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
                blended(constructor.id, "Q", q + bonus),
                blended(constructor.id, "S", sum(m.sprint for m in members))
                if weekend.sprint
                else 0,
                blended(constructor.id, "R", sum(m.race for m in members)),
            )
    return output
