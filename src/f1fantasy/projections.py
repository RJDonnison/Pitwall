"""Pre-weekend predictions from completed Fantasy scores and FastF1 form."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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
from .risk import expected_session_points, reliability_components
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


@lru_cache(maxsize=256)
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
    use_risk: bool = True,
    use_model: bool = True,
    return_features: bool = False,
) -> (
    dict[tuple[int, str], Estimate]
    | tuple[
        dict[tuple[int, str], Estimate],
        dict[tuple[int, str], dict[str, dict[str, float]]],
    ]
):
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
    features: dict[tuple[int, str], dict[str, dict[str, float]]] = {}

    def component(
        asset: Asset,
        index: int,
        kind: str,
        fastf1_form: float,
        baseline: float,
        telemetry_delta: float = 0,
        team_form: float | None = None,
        severe_probability: float = 0,
        classified_points: float | None = None,
    ) -> dict[str, float]:
        own = fantasy_history.get(asset.id, {}).get(kind, [])
        track_visits = track[index].get(asset.tla, {}).get(kind, [])
        return {
            "baseline": float(baseline),
            "fastf1_form": float(fastf1_form),
            "official_form": float(mean(own, fastf1_form)),
            "recent3": float(sum(own[-3:]) / len(own[-3:]) if own else baseline),
            "team_form": float(team_form if team_form is not None else baseline),
            "circuit_form": float(season_mean(track_visits, fastf1_form)),
            "telemetry_delta": float(telemetry_delta),
            "severe_probability": float(severe_probability),
            "classified_points": float(
                classified_points if classified_points is not None else baseline
            ),
        }

    for index, weekend in enumerate(weekends):
        for driver in drivers:
            base = history.get(driver.tla, {})
            q_base = season_mean(base.get("Q", []), 0)
            r_base = season_mean(base.get("R", []), 0)
            q = track_adjusted(
                index, driver.tla, "Q", q_base, blended(driver.id, "Q", q_base)
            )
            race_forecast = (
                expected_session_points(driver, "R", fantasy_history, drivers, r_base)
                if use_risk
                else blended(driver.id, "R", r_base)
            )
            r = track_adjusted(index, driver.tla, "R", r_base, race_forecast)
            sprint_results = base.get("S", [])
            if use_risk:
                race_reference = max(0, r) * 0.35
                s_base = (
                    len(sprint_results) * season_mean(sprint_results, race_reference)
                    + 4 * race_reference
                ) / (len(sprint_results) + 4)
                sprint_forecast = expected_session_points(
                    driver,
                    "S",
                    fantasy_history,
                    drivers,
                    s_base,
                    race_finish_reference=r,
                )
            else:
                s_base = season_mean(sprint_results, r * 0.35)
                sprint_forecast = blended(driver.id, "S", s_base)
            s = (
                track_adjusted(index, driver.tla, "S", s_base, sprint_forecast)
                if weekend.sprint
                else 0.0
            )
            q_delta, s_delta, r_delta = telemetry.get(
                (index, driver.id), (0.0, 0.0, 0.0)
            )
            q, s, r = q + q_delta, s + s_delta, r + r_delta
            output[index, driver.id] = Estimate(q, s, r)
            teammate = next(
                (
                    a
                    for a in drivers
                    if a.team_id == driver.team_id and a.id != driver.id
                ),
                None,
            )
            risk = reliability_components(driver, "R", fantasy_history, drivers, r_base)
            features[index, driver.id] = {}
            for phase, key, base_score, score, delta in (
                ("qualifying", "Q", q_base, q, q_delta),
                ("sprint", "S", s_base, s, s_delta),
                ("race", "R", r_base, r, r_delta),
            ):
                teammate_scores = (
                    fantasy_history.get(teammate.id, {}).get(key, [])
                    if teammate is not None
                    else []
                )
                partner_form = (
                    mean(teammate_scores, score) if teammate_scores else score
                )
                features[index, driver.id][phase] = component(
                    driver,
                    index,
                    key,
                    base_score,
                    score,
                    delta,
                    partner_form,
                    risk.severe_probability if phase == "race" else 0,
                    risk.classified_points if phase == "race" else score,
                )
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
            features[index, constructor.id] = {}
            for phase, key in (("qualifying", "Q"), ("sprint", "S"), ("race", "R")):
                member_values = [getattr(m, phase) for m in members]
                score = getattr(output[index, constructor.id], phase)
                features[index, constructor.id][phase] = component(
                    constructor,
                    index,
                    key,
                    sum(member_values),
                    score,
                    team_form=sum(member_values),
                )
    if use_model and use_risk and use_telemetry:
        # Training imports backtest -> projections; import locally to avoid a
        # cycle and never use a model to generate its own training examples.
        from .training import load_model

        model = load_model(first.season)
        if (
            model is not None
            and model["active"]
            and model["last_completed_round"] < first.round
        ):
            legacy = estimate_assets(
                assets,
                weekends,
                lookback,
                use_telemetry=use_telemetry,
                use_risk=False,
                use_model=False,
            )
            for index, _weekend in enumerate(weekends):
                for asset in assets:
                    current, older = output[index, asset.id], legacy[index, asset.id]
                    weights = model["weights"][asset.kind]
                    naive_values = fantasy_history.get(asset.id, {}).get("R", [])[-3:]
                    naive = (
                        sum(naive_values) / len(naive_values)
                        if naive_values
                        else current.race
                    )
                    output[index, asset.id] = Estimate(
                        weights["qualifying"][0] * current.qualifying
                        + weights["qualifying"][1] * older.qualifying,
                        weights["sprint"][0] * current.sprint
                        + weights["sprint"][1] * older.sprint,
                        weights["race"][0] * current.race
                        + weights["race"][1] * older.race
                        + weights["race"][2] * naive,
                    )
    return (output, features) if return_features else output
