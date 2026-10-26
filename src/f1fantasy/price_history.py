"""Verified pre-lock price snapshots for future budget-legal backtests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .data import Asset, DataError, Snapshot, Weekend

VERSION = 1
DEFAULT_PRICE_DIR = Path(".f1fantasy/cache/prices")


def _path(season: int, round_number: int, directory: Path) -> Path:
    return directory / f"{season}-{round_number:02d}.json"


def save_verified(snapshot: Snapshot, directory: Path = DEFAULT_PRICE_DIR) -> bool:
    """Record only current, cross-checked Fantasy prices before the weekend."""
    if (
        snapshot.provisional
        or snapshot.statistics is None
        or snapshot.weekend.locked
        or snapshot.fetched_at >= snapshot.weekend.first_session
    ):
        return False
    data = {
        "version": VERSION,
        "season": snapshot.weekend.season,
        "round": snapshot.weekend.round,
        "gameday_id": snapshot.weekend.gameday_id,
        "checked_at": snapshot.fetched_at.isoformat(),
        "source_published_at": snapshot.published_at.isoformat(),
        "first_session": snapshot.weekend.first_session.isoformat(),
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "kind": a.kind,
                "team_id": a.team_id,
                "price": a.price,
                "tla": a.tla,
            }
            for a in snapshot.assets
        ],
    }
    path = _path(snapshot.weekend.season, snapshot.weekend.round, directory)
    if path.exists():
        existing = json.loads(path.read_text())
        if datetime.fromisoformat(existing["checked_at"]) >= snapshot.fetched_at:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, allow_nan=False))
    temp.replace(path)
    return True


def load_verified(
    weekend: Weekend, directory: Path = DEFAULT_PRICE_DIR
) -> tuple[Asset, ...] | None:
    path = _path(weekend.season, weekend.round, directory)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if (
            data["version"] != VERSION
            or data["season"] != weekend.season
            or data["round"] != weekend.round
            or data["gameday_id"] != weekend.gameday_id
            or datetime.fromisoformat(data["checked_at"]) >= weekend.first_session
            or datetime.fromisoformat(data["source_published_at"])
            >= weekend.first_session
        ):
            raise DataError("Price snapshot is not from before the predicted weekend")
        assets = tuple(
            Asset(
                str(row["id"]),
                str(row["name"]),
                str(row["kind"]),
                str(row["team_id"]),
                int(row["price"]),
                str(row.get("tla", "")),
            )
            for row in data["assets"]
        )
        if (
            len({a.id for a in assets}) != len(assets)
            or sum(a.kind == "DRIVER" for a in assets) < 19
            or sum(a.kind == "CONSTRUCTOR" for a in assets) < 9
        ):
            raise DataError("Incomplete archived pre-lock roster")
        return assets
    except (OSError, TypeError, KeyError, ValueError) as exc:
        raise DataError(f"Cannot verify saved price snapshot {path}: {exc}") from exc
