from datetime import datetime, timezone

import pytest

from f1fantasy import data


def test_upcoming_sprint_is_grouped_and_locked(monkeypatch):
    fixtures = [
        {
            "Season": "2026",
            "IsPostponed": 0,
            "GamedayId": 2,
            "MeetingNumber": 2,
            "MeetingName": "China",
            "SessionName": name,
            "GDIsLocked": 0,
            "SessionStartDateISO8601": date,
            "SessionEndDateISO8601": date,
        }
        for name, date in (
            ("Sprint Qualifying", "2026-03-01T12:00:00+00:00"),
            ("Qualifying", "2026-03-02T12:00:00+00:00"),
            ("Race", "2026-03-03T12:00:00+00:00"),
        )
    ]
    monkeypatch.setattr(data, "_get_json", lambda _: {"fixtures": fixtures})
    result = data.upcoming_weekends(2026, datetime(2026, 2, 28, tzinfo=timezone.utc))
    assert len(result) == 1
    assert result[0].sprint and result[0].gameday_id == 2


def test_rejects_missing_prices_or_constructor(monkeypatch):
    rows = [
        {
            "IsActive": "1",
            "PositionName": "DRIVER",
            "Value": 5.0,
            "PlayerId": i,
            "FUllName": f"Driver {i}",
            "TeamId": "missing",
            "DriverTLA": "AAA",
        }
        for i in range(20)
    ]
    rows += [
        {
            "IsActive": "1",
            "PositionName": "CONSTRUCTOR",
            "Value": 5.0,
            "PlayerId": f"c{i}",
            "FUllName": f"Team {i}",
            "TeamId": f"t{i}",
        }
        for i in range(10)
    ]
    monkeypatch.setattr(
        data,
        "_get_json",
        lambda _: {
            "Value": rows,
            "FeedTime": {
                "UTCTime": datetime.now(timezone.utc).strftime("%m/%d/%Y %I:%M:%S %p")
            },
        },
    )
    with pytest.raises(data.DataError, match="mapping"):
        data.load_assets(1)
    rows[0].pop("Value")
    with pytest.raises(data.DataError, match="prices"):
        data.load_assets(1)


def test_official_weekend_total_and_bonus_history(monkeypatch):
    rows = [
        {
            "IsActive": "1",
            "PlayerId": str(i),
            "QualifyingPoints": "3",
            "SprintPoints": "2",
            "RacePoints": "6",
            "GamedayPoints": "16",
        }
        for i in range(30)
    ]
    monkeypatch.setattr(data, "_get_json", lambda _: {"Value": rows})
    scores = data.completed_scores(2, sprint=True)
    assert scores["0"] == (3.0, 2.0, 11.0)
    rows[0].pop("GamedayPoints")
    with pytest.raises(data.DataError, match="Unverifiable"):
        data.completed_scores(2, sprint=True)
