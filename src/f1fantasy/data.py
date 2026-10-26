"""Live Fantasy roster/prices and FastF1 event metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import fastf1
import requests

BASE = "https://fantasy.formula1.com/feeds"


class DataError(ValueError):
    """A required live source could not be verified."""


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    kind: str
    team_id: str
    price: int  # $0.1m units, avoiding floating-point budget mistakes
    tla: str = ""


@dataclass(frozen=True)
class Weekend:
    season: int
    round: int
    name: str
    gameday_id: int
    first_session: datetime
    sprint: bool
    locked: bool
    last_session: datetime | None = None


@dataclass(frozen=True)
class Snapshot:
    weekend: Weekend
    assets: tuple[Asset, ...]
    fetched_at: datetime
    published_at: datetime


def _get_json(path: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{BASE}/{path}",
            headers={"Cache-Control": "no-cache"},
            params={"at": int(datetime.now(timezone.utc).timestamp())},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("Data"), dict):
            raise DataError(f"Malformed Fantasy feed: {path}")
        return payload["Data"]
    except (requests.RequestException, ValueError) as exc:
        raise DataError(f"Cannot verify Fantasy feed {path}: {exc}") from exc


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise DataError("Fantasy session lacks UTC offset")
    return result.astimezone(timezone.utc)


def season_weekends(season: int) -> list[Weekend]:
    """Return scheduled race weekends, including earlier completed rounds."""
    fixtures = _get_json("v2/schedule/raceday_en.json").get("fixtures")
    if not isinstance(fixtures, list):
        raise DataError("Fantasy schedule has no fixtures")
    groups: dict[int, list[dict[str, Any]]] = {}
    try:
        for fixture in fixtures:
            if int(fixture["Season"]) == season and int(fixture["IsPostponed"]) == 0:
                groups.setdefault(int(fixture["GamedayId"]), []).append(fixture)
        weekends = []
        for gameday, sessions in groups.items():
            start = min(_timestamp(s["SessionStartDateISO8601"]) for s in sessions)
            first = min(
                sessions, key=lambda s: _timestamp(s["SessionStartDateISO8601"])
            )
            weekends.append(
                Weekend(
                    season,
                    int(first["MeetingNumber"]),
                    first["MeetingName"],
                    gameday,
                    start,
                    any("Sprint" in s["SessionName"] for s in sessions),
                    bool(int(first["GDIsLocked"])),
                    max(_timestamp(s["SessionEndDateISO8601"]) for s in sessions),
                )
            )
        return sorted(weekends, key=lambda w: w.first_session)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError(f"Cannot verify Fantasy schedule: {exc}") from exc


def upcoming_weekends(season: int, now: datetime | None = None) -> list[Weekend]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DataError("Current time must have a timezone")
    return [w for w in season_weekends(season) if w.first_session > now]


def load_assets(gameday_id: int) -> tuple[tuple[Asset, ...], datetime]:
    feed = _get_json(f"drivers/{gameday_id}_en.json")
    rows = feed.get("Value")
    if not isinstance(rows, list):
        raise DataError("Fantasy roster has no values")
    try:
        published = datetime.strptime(
            feed["FeedTime"]["UTCTime"], "%m/%d/%Y %I:%M:%S %p"
        ).replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("Fantasy prices lack a valid source timestamp") from exc
    age = datetime.now(timezone.utc) - published
    if age < -timedelta(minutes=5) or age > timedelta(days=45):
        raise DataError("Fantasy price feed is stale or dated in the future")
    assets: list[Asset] = []
    try:
        for row in rows:
            if str(row["IsActive"]) != "1":
                continue
            kind = str(row["PositionName"])
            if kind not in {"DRIVER", "CONSTRUCTOR"}:
                raise DataError(f"Unknown asset type: {kind}")
            amount = Decimal(str(row["Value"])) * 10
            if (
                not amount.is_finite()
                or amount != amount.to_integral_value()
                or amount < 30
                or amount > 340
            ):
                raise DataError(f"Invalid Fantasy price for {row['PlayerId']}")
            assets.append(
                Asset(
                    str(row["PlayerId"]),
                    str(row["FUllName"]),
                    kind,
                    str(row["TeamId"]),
                    int(amount),
                    str(row.get("DriverTLA", "")),
                )
            )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise DataError(f"Cannot verify Fantasy roster/prices: {exc}") from exc
    if len({a.id for a in assets}) != len(assets):
        raise DataError("Duplicate active Fantasy IDs")
    # Fail closed on incomplete or mismatched season/round feeds.
    drivers = [a for a in assets if a.kind == "DRIVER"]
    constructors = [a for a in assets if a.kind == "CONSTRUCTOR"]
    if len(drivers) < 20 or len(constructors) < 10 or any(not a.tla for a in drivers):
        raise DataError("Incomplete active driver/constructor roster")
    if not {d.team_id for d in drivers}.issubset({c.team_id for c in constructors}):
        raise DataError("Driver/constructor mapping is incomplete")
    return tuple(assets), published


def completed_scores(
    gameday_id: int, sprint: bool
) -> dict[str, tuple[float, float, float]]:
    """Official per-weekend Fantasy scores, including awarded bonus categories.

    Call only for a weekend known to have completed *before* the prediction.
    The feed also contains cumulative season statistics; those are intentionally
    ignored because they can contain information from later events.
    """
    feed = _get_json(f"drivers/{gameday_id}_en.json")
    rows = feed.get("Value")
    if not isinstance(rows, list) or len(rows) < 30:
        raise DataError(f"Incomplete Fantasy scores for race week {gameday_id}")
    output: dict[str, tuple[float, float, float]] = {}
    try:
        for item in rows:
            if str(item["IsActive"]) != "1":
                continue
            key = str(item["PlayerId"])
            q = Decimal(str(item["QualifyingPoints"]))
            r = Decimal(str(item["RacePoints"]))
            s = Decimal(str(item["SprintPoints"])) if sprint else Decimal(0)
            total = Decimal(str(item["GamedayPoints"]))
            if not all(n.is_finite() for n in (q, r, s, total)) or key in output:
                raise DataError(f"Invalid Fantasy scores for race week {gameday_id}")
            # Occasionally the displayed session subtotals differ from the final
            # official weekend score. Preserve the final score in the race bucket.
            output[key] = (float(q), float(s), float(total - q - s))
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise DataError(
            f"Unverifiable Fantasy scores for race week {gameday_id}: {exc}"
        ) from exc
    if len(output) < 30:
        raise DataError(f"Incomplete Fantasy scores for race week {gameday_id}")
    return output


def snapshot(
    season: int, now: datetime | None = None
) -> tuple[Snapshot, list[Weekend]]:
    weekends = upcoming_weekends(season, now)
    if not weekends:
        raise DataError(f"No upcoming Fantasy weekend for {season}")
    first = weekends[0]
    if first.locked:
        raise DataError(f"Fantasy team for {first.name} is locked or not open yet")
    assets, published = load_assets(first.gameday_id)
    return Snapshot(first, assets, datetime.now(timezone.utc), published), weekends


def fastf1_weekend(weekend: Weekend) -> Any:
    """Check FastF1's round and format against Fantasy's schedule."""
    try:
        event = fastf1.get_event(weekend.season, weekend.round)
        if ("sprint" in str(event["EventFormat"]).lower()) != weekend.sprint:
            raise DataError(f"Conflicting Sprint format for {weekend.name}")
        return event
    except DataError:
        raise
    except Exception as exc:
        raise DataError(f"Cannot verify FastF1 event {weekend.name}: {exc}") from exc
