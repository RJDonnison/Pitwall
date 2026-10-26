"""Prior-season labels for chronological calibration, with explicit provenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

import fastf1
import pandas as pd
from fastf1.exceptions import RateLimitExceededError

from .data import Asset, DataError, Weekend
from .history import DEFAULT_CACHE, RATE_LIMIT_MESSAGE, configure_cache
from .projections import Estimate, _session_scores

PROXY_VERSION = 1


@dataclass(frozen=True)
class PriorWeek:
    weekend: Weekend
    assets: tuple[Asset, ...]
    scores: dict[str, Estimate]


def _calendar(year: int) -> list[Weekend]:
    weekends = []
    for _, row in fastf1.get_event_schedule(year, include_testing=False).iterrows():
        number = int(row["RoundNumber"])
        if number < 1:
            continue
        event = fastf1.get_event(year, number)
        start = (
            event.get_session_date(1, utc=True)
            .to_pydatetime()
            .replace(tzinfo=timezone.utc)
        )
        end = (
            event.get_session_date("Race", utc=True)
            .to_pydatetime()
            .replace(tzinfo=timezone.utc)
        )
        weekends.append(
            Weekend(
                year,
                number,
                str(event["EventName"]),
                number,
                start,
                "sprint" in str(event["EventFormat"]).lower(),
                True,
                end + timedelta(hours=3),
            )
        )
    return sorted(weekends, key=lambda w: w.first_session)


def _serialize(week: PriorWeek) -> dict:
    return {
        "round": week.weekend.round,
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "kind": a.kind,
                "team_id": a.team_id,
                "tla": a.tla,
                "qualifying": week.scores[a.id].qualifying,
                "sprint": week.scores[a.id].sprint,
                "race": week.scores[a.id].race,
            }
            for a in week.assets
        ],
    }


def _parse(source: dict, season: int, calendar: list[Weekend]) -> list[PriorWeek]:
    if int(source.get("season", -1)) != season or not isinstance(
        source.get("weeks"), list
    ):
        raise DataError("Prior-season file lacks the requested season and weeks")
    by_round = {week.round: week for week in calendar}
    results: list[PriorWeek] = []
    for row in source["weeks"]:
        try:
            event = by_round[int(row["round"])]
            assets, scores = [], {}
            for participant in row["assets"]:
                id_ = str(participant["id"])
                kind = participant["kind"]
                if id_ in scores or kind not in ("DRIVER", "CONSTRUCTOR"):
                    raise DataError(f"Duplicate or invalid prior-season asset {id_}")
                asset = Asset(
                    id_,
                    str(participant["name"]),
                    kind,
                    str(participant["team_id"]),
                    30,
                    str(participant.get("tla", "")),
                )
                points = Estimate(
                    *(
                        float(participant[key])
                        for key in ("qualifying", "sprint", "race")
                    )
                )
                if any(
                    not isfinite(value) or abs(value) > 500
                    for value in (points.qualifying, points.sprint, points.race)
                ):
                    raise DataError(f"Invalid prior-season points for {id_}")
                if not event.sprint and points.sprint != 0:
                    raise DataError(f"Unexpected Sprint points in {event.name}")
                assets.append(asset)
                scores[id_] = points
            drivers = [a for a in assets if a.kind == "DRIVER"]
            constructors = [a for a in assets if a.kind == "CONSTRUCTOR"]
            if len(drivers) < 19 or len(constructors) < 9:
                raise DataError(f"Incomplete prior-season roster for {event.name}")
            if any(
                sum(a.team_id == team.team_id for a in drivers) != 2
                for team in constructors
            ):
                raise DataError(
                    f"Prior-season teams have incomplete driver pairs: {event.name}"
                )
            results.append(PriorWeek(event, tuple(assets), scores))
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, DataError):
                raise
            raise DataError(f"Invalid prior-season race entry: {exc}") from exc
    if len({w.weekend.round for w in results}) != len(results) or len(results) < 8:
        raise DataError("Prior season requires at least eight unique race-week records")
    return sorted(results, key=lambda w: w.weekend.first_session)


def load_previous_season(
    season: int, *, official_file: Path | None = None, root: Path = DEFAULT_CACHE
) -> tuple[list[PriorWeek], str]:
    """Use user-supplied Fantasy labels or explicitly approximate from FastF1."""
    year = season - 1
    configure_cache(root)
    try:
        calendar = _calendar(year)
        if official_file is not None:
            return _parse(
                json.loads(official_file.read_text()), year, calendar
            ), "imported_official"
        cache = root / "prior-proxy" / f"v{PROXY_VERSION}-{year}.json"
        if cache.exists():
            return _parse(json.loads(cache.read_text()), year, calendar), "fastf1_proxy"
        prior = []

        def team_id(row):
            value = row.get("TeamId")
            return str(row["TeamName"] if pd.isna(value) or not value else value)

        for event in calendar:
            q = _session_scores(year, event.round, "Q")
            r = _session_scores(year, event.round, "R")
            s = _session_scores(year, event.round, "S") if event.sprint else {}
            session = fastf1.get_session(year, event.round, "R")
            session.load(laps=False, telemetry=False, weather=False, messages=False)
            drivers, scores = [], {}
            for _, row in session.results.iterrows():
                tla = str(row["Abbreviation"])
                team = team_id(row)
                if tla not in r or tla not in q:
                    continue
                drivers.append(
                    Asset(tla, str(row["FullName"]), "DRIVER", team, 30, tla)
                )
                scores[tla] = Estimate(q[tla], s.get(tla, 0.0), r[tla])
            constructors = []
            for team in sorted({a.team_id for a in drivers}):
                members = [a for a in drivers if a.team_id == team]
                if len(members) != 2:
                    continue
                id_ = f"TEAM:{team}"
                constructors.append(
                    Asset(
                        id_,
                        str(
                            next(
                                row["TeamName"]
                                for _, row in session.results.iterrows()
                                if team_id(row) == team
                            )
                        ),
                        "CONSTRUCTOR",
                        team,
                        30,
                    )
                )
                both_q = sum(scores[a.id].qualifying for a in members)
                bonus = (
                    10
                    if all(scores[a.id].qualifying > 0 for a in members)
                    else (
                        3 if any(scores[a.id].qualifying > 0 for a in members) else -1
                    )
                )
                scores[id_] = Estimate(
                    both_q + bonus,
                    sum(scores[a.id].sprint for a in members),
                    sum(scores[a.id].race for a in members),
                )
            prior.append(PriorWeek(event, tuple(drivers + constructors), scores))
        payload = {
            "version": PROXY_VERSION,
            "season": year,
            "weeks": [_serialize(week) for week in prior],
        }
        result = _parse(payload, year, calendar)
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, allow_nan=False))
        temporary.replace(cache)
        return result, "fastf1_proxy"
    except RateLimitExceededError as exc:
        raise DataError(RATE_LIMIT_MESSAGE) from exc
    except (OSError, ValueError, KeyError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(f"Cannot verify prior-season data: {exc}") from exc
