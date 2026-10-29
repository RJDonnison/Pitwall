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


class RosterNotPublished(DataError):
    """The requested race-week roster feed is available but empty."""


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    kind: str
    team_id: str
    price: int  # $0.1m units, avoiding floating-point budget mistakes
    tla: str = ""
    season_points: float | None = None


@dataclass(frozen=True)
class Statistic:
    id: str
    kind: str
    name: str
    price: int
    season_points: float


@dataclass(frozen=True)
class StatisticsSnapshot:
    season: int
    entries: tuple[Statistic, ...]
    fetched_at: datetime


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
    price_weekend: Weekend | None = None
    statistics: StatisticsSnapshot | None = None

    @property
    def provisional(self) -> bool:
        return (
            self.price_weekend is not None
            and self.price_weekend.gameday_id != self.weekend.gameday_id
        )


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


def load_assets(
    gameday_id: int, *, require_recent: bool = True
) -> tuple[tuple[Asset, ...], datetime]:
    """Load a full race-week roster; older feeds are for historical evaluation only."""
    feed = _get_json(f"drivers/{gameday_id}_en.json")
    rows = feed.get("Value")
    if not isinstance(rows, list):
        raise DataError("Fantasy roster has no values")
    if not rows:
        raise RosterNotPublished(
            f"Fantasy roster for race week {gameday_id} has not been published yet"
        )
    try:
        published = datetime.strptime(
            feed["FeedTime"]["UTCTime"], "%m/%d/%Y %I:%M:%S %p"
        ).replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("Fantasy prices lack a valid source timestamp") from exc
    age = datetime.now(timezone.utc) - published
    if age < -timedelta(minutes=5) or (require_recent and age > timedelta(days=45)):
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
                    (
                        float(Decimal(str(row["OverallPpints"])))
                        if row.get("OverallPpints") not in (None, "")
                        else None
                    ),
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
    if any(sum(d.team_id == c.team_id for d in drivers) != 2 for c in constructors):
        raise DataError("Expected exactly two active drivers for each constructor")
    return tuple(assets), published


def load_statistics(
    season: int, assets: tuple[Asset, ...] | None = None
) -> StatisticsSnapshot:
    """Cross-check the same official rankings shown on the Fantasy Statistics page."""
    feed = _get_json("v2/statistics/driverconstructors_4.json")
    try:
        if int(feed["season"]) != season:
            raise DataError("Statistics season does not match the Fantasy schedule")
        entries = []
        for section, kind in (("driver", "DRIVER"), ("constructor", "CONSTRUCTOR")):
            points = next(
                block for block in feed[section] if block["config"]["key"] == "fPoints"
            )
            for row in points["participants"]:
                price = Decimal(str(row["curvalue"])) * 10
                total = Decimal(str(row["statvalue"]))
                if (
                    not price.is_finite()
                    or price != price.to_integral_value()
                    or not total.is_finite()
                ):
                    raise DataError(
                        "Statistics contains invalid prices or season points"
                    )
                entries.append(
                    Statistic(
                        str(row["playerid"]),
                        kind,
                        str(row["playername"] or row["teamname"]),
                        int(price),
                        float(total),
                    )
                )
        if len({entry.id for entry in entries}) != len(entries):
            raise DataError("Statistics contains duplicate Fantasy IDs")
        if assets is not None:
            known = {entry.id: entry for entry in entries}
            for asset in assets:
                row = known.get(asset.id)
                if row is None or row.kind != asset.kind:
                    raise DataError(
                        f"Statistics missing active {asset.kind.lower()} {asset.name}"
                    )
                if row.price != asset.price:
                    raise DataError(
                        f"Statistics price disagrees with race-week feed for {asset.name}"
                    )
                if (
                    asset.season_points is not None
                    and row.season_points != asset.season_points
                ):
                    raise DataError(
                        f"Statistics points disagree with race-week feed for {asset.name}"
                    )
        return StatisticsSnapshot(season, tuple(entries), datetime.now(timezone.utc))
    except (KeyError, TypeError, ValueError, StopIteration, InvalidOperation) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(f"Cannot verify Fantasy Statistics page feed: {exc}") from exc


def completed_scores(
    gameday_id: int, sprint: bool
) -> dict[str, tuple[float, float, float]]:
    """Official per-weekend Fantasy scores, including awarded bonus categories.

    Call only for a weekend known to have completed *before* the prediction.
    The feed also contains cumulative season statistics; those are intentionally
    ignored because they can contain information from later events.
    """
    from .public_history import fantasy_feed

    feed = fantasy_feed(f"drivers/{gameday_id}_en.json", _get_json)
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
    season: int, now: datetime | None = None, *, allow_old_prices: bool = False
) -> tuple[Snapshot, list[Weekend]]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DataError("Current time must have a timezone")
    schedule = season_weekends(season)
    weekends = [w for w in schedule if w.first_session > now]
    if not weekends:
        raise DataError(f"No upcoming Fantasy weekend for {season}")
    first = weekends[0]
    if first.locked and not allow_old_prices:
        raise DataError(f"Fantasy team for {first.name} is locked or not open yet")
    finished = [w for w in schedule if w.last_session and w.last_session < now]
    price_weekend = first
    try:
        assets, published = load_assets(first.gameday_id)
    except DataError as exc:
        if not (allow_old_prices and isinstance(exc, RosterNotPublished) and finished):
            raise
        price_weekend = finished[-1]
        # The previous feed must itself be current and have been updated after
        # that race. Its prices/roster are explicitly provisional for next week.
        assets, published = load_assets(price_weekend.gameday_id)
        if published < price_weekend.last_session:
            raise DataError(
                "Previous race prices have not been updated since its finish"
            ) from exc
    if finished:
        last = finished[-1]
        if price_weekend == first:
            previous, _ = load_assets(last.gameday_id, require_recent=False)
            if published < last.last_session:
                raise DataError("Upcoming prices predate the previous race result")
            for kind in ("DRIVER", "CONSTRUCTOR"):
                if sum(a.kind == kind for a in assets) != sum(
                    a.kind == kind for a in previous
                ):
                    raise DataError(
                        "Upcoming Fantasy roster differs in size from the last verified round"
                    )
    stats = load_statistics(season, assets) if price_weekend == first else None
    return Snapshot(
        first, assets, datetime.now(timezone.utc), published, price_weekend, stats
    ), weekends


def fastf1_weekend(weekend: Weekend) -> Any:
    """Check FastF1's round, race date and format against Fantasy's schedule."""
    try:
        from .public_history import event as get_event

        event = get_event(weekend.season, weekend.round)
        if ("sprint" in str(event["EventFormat"]).lower()) != weekend.sprint:
            raise DataError(f"Conflicting Sprint format for {weekend.name}")
        if weekend.last_session is not None:
            race_date = (
                event.get_session_date("Race", utc=True)
                .to_pydatetime()
                .replace(tzinfo=timezone.utc)
            )
            if not (
                weekend.first_session
                <= race_date
                <= weekend.last_session + timedelta(hours=3)
            ):
                raise DataError(
                    f"FastF1 race date disagrees with Fantasy event {weekend.name}"
                )
        return event
    except DataError:
        raise
    except Exception as exc:
        raise DataError(f"Cannot verify FastF1 event {weekend.name}: {exc}") from exc
