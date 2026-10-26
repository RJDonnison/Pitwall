import json
from datetime import datetime, timedelta, timezone

import pytest

from f1fantasy.data import Asset, DataError, Snapshot, StatisticsSnapshot, Weekend
from f1fantasy.price_history import load_verified, save_verified


def test_early_cross_checked_snapshot_is_available_after_race(tmp_path):
    now = datetime.now(timezone.utc)
    event = Weekend(2026, 3, "Test", 3, now + timedelta(days=7), False, False)
    roster = tuple(
        [
            Asset(str(i), f"Driver {i}", "DRIVER", str(i // 2), 50, f"D{i}")
            for i in range(20)
        ]
        + [Asset(f"c{i}", f"Team {i}", "CONSTRUCTOR", str(i), 100) for i in range(10)]
    )
    verified = Snapshot(
        event,
        roster,
        now,
        now - timedelta(hours=1),
        event,
        StatisticsSnapshot(2026, (), now),
    )
    assert save_verified(verified, tmp_path)
    assert not save_verified(verified, tmp_path)
    assert load_verified(event, tmp_path) == roster
    path = tmp_path / "2026-03.json"
    data = json.loads(path.read_text())
    data["checked_at"] = (event.first_session + timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(data))
    with pytest.raises(DataError, match="not from before"):
        load_verified(event, tmp_path)


def test_provisional_roster_cannot_be_archived(tmp_path):
    now = datetime.now(timezone.utc)
    event = Weekend(2026, 3, "Test", 3, now + timedelta(days=7), False, False)
    previous = Weekend(2026, 2, "Prior", 2, now - timedelta(days=7), False, True)
    assert not save_verified(Snapshot(event, (), now, now, previous), tmp_path)
    assert load_verified(event, tmp_path) is None
