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


def test_unopened_raceweek_fails_without_falling_back_to_old_prices(monkeypatch):
    monkeypatch.setattr(data, "_get_json", lambda _: {"Value": []})
    with pytest.raises(data.DataError, match="not been published"):
        data.load_assets(19)


def test_fastf1_event_must_match_fantasy_race_date(monkeypatch):
    import pandas as pd

    class Event(dict):
        def get_session_date(self, *_args, **_kwargs):
            return pd.Timestamp("2026-06-01")

    monkeypatch.setattr(
        data.fastf1, "get_event", lambda *_: Event(EventFormat="conventional")
    )
    weekend = data.Weekend(
        2026,
        4,
        "Miami",
        4,
        datetime(2026, 5, 2, tzinfo=timezone.utc),
        False,
        False,
        datetime(2026, 5, 3, tzinfo=timezone.utc),
    )
    with pytest.raises(data.DataError, match="disagrees"):
        data.fastf1_weekend(weekend)


def test_snapshot_rejects_partial_next_roster(monkeypatch):
    previous = data.Weekend(
        2026,
        18,
        "USA",
        18,
        datetime(2026, 10, 24, tzinfo=timezone.utc),
        False,
        True,
        datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    upcoming = data.Weekend(
        2026,
        19,
        "Mexico",
        19,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
        False,
        False,
    )
    monkeypatch.setattr(data, "season_weekends", lambda _: [previous, upcoming])

    def roster(week, *, require_recent=True):
        count = 10 if week == 19 else 11
        assets = tuple(
            data.Asset(str(i), str(i), "DRIVER", str(i // 2), 50, "AAA")
            for i in range(count * 2)
        ) + tuple(
            data.Asset(f"c{i}", str(i), "CONSTRUCTOR", str(i), 50) for i in range(count)
        )
        return assets, datetime(2026, 10, 26, tzinfo=timezone.utc)

    monkeypatch.setattr(data, "load_assets", roster)
    with pytest.raises(data.DataError, match="differs in size"):
        data.snapshot(2026, datetime(2026, 10, 27, tzinfo=timezone.utc))


def test_every_snapshot_refetches_prices_and_rejects_an_empty_update(monkeypatch):
    next_race = data.Weekend(
        2026, 1, "Opening", 1, datetime(2026, 11, 1, tzinfo=timezone.utc), False, False
    )
    monkeypatch.setattr(data, "season_weekends", lambda _: [next_race])
    rows = [
        {
            "IsActive": "1",
            "PositionName": "DRIVER",
            "Value": 5,
            "PlayerId": str(i),
            "FUllName": f"Driver {i}",
            "TeamId": str(i // 2),
            "DriverTLA": f"D{i}",
        }
        for i in range(20)
    ] + [
        {
            "IsActive": "1",
            "PositionName": "CONSTRUCTOR",
            "Value": 5,
            "PlayerId": f"c{i}",
            "FUllName": f"Team {i}",
            "TeamId": str(i),
        }
        for i in range(10)
    ]
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "Data": {
                    "Value": rows if len(calls) == 1 else [],
                    "FeedTime": {
                        "UTCTime": datetime.now(timezone.utc).strftime(
                            "%m/%d/%Y %I:%M:%S %p"
                        )
                    },
                }
            }

    def get(*_args, **_kwargs):
        calls.append(1)
        return Response()

    monkeypatch.setattr(data.requests, "get", get)
    assert (
        len(data.snapshot(2026, datetime(2026, 10, 26, tzinfo=timezone.utc))[0].assets)
        == 30
    )
    with pytest.raises(data.DataError, match="not been published"):
        data.snapshot(2026, datetime(2026, 10, 26, tzinfo=timezone.utc))
    assert len(calls) == 2


def test_explicit_old_prices_preview_uses_only_recent_completed_feed(monkeypatch):
    previous = data.Weekend(
        2026,
        18,
        "USA",
        18,
        datetime(2026, 10, 24, tzinfo=timezone.utc),
        False,
        True,
        datetime(2026, 10, 25, 20, tzinfo=timezone.utc),
    )
    upcoming = data.Weekend(
        2026,
        19,
        "Mexico",
        19,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
        False,
        False,
    )
    monkeypatch.setattr(data, "season_weekends", lambda _: [previous, upcoming])
    calls = []

    def roster(week, *, require_recent=True):
        calls.append((week, require_recent))
        if week == 19:
            raise data.RosterNotPublished("Next week has no roster")
        return (data.Asset("c", "Team", "CONSTRUCTOR", "t", 50),), datetime(
            2026, 10, 25, 22, tzinfo=timezone.utc
        )

    monkeypatch.setattr(data, "load_assets", roster)
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    with pytest.raises(data.RosterNotPublished):
        data.snapshot(2026, now)
    snap, weeks = data.snapshot(2026, now, allow_old_prices=True)
    assert (
        snap.provisional and snap.weekend == upcoming and snap.price_weekend == previous
    )
    assert weeks[0] == upcoming
    assert calls == [(19, True), (19, True), (18, True)]


def test_old_prices_flag_does_not_hide_bad_price_data(monkeypatch):
    previous = data.Weekend(
        2026,
        18,
        "USA",
        18,
        datetime(2026, 10, 24, tzinfo=timezone.utc),
        False,
        True,
        datetime(2026, 10, 25, 20, tzinfo=timezone.utc),
    )
    upcoming = data.Weekend(
        2026,
        19,
        "Mexico",
        19,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
        False,
        False,
    )
    monkeypatch.setattr(data, "season_weekends", lambda _: [previous, upcoming])
    called = []

    def roster(week, *, require_recent=True):
        called.append(week)
        raise data.DataError("Invalid Fantasy price")

    monkeypatch.setattr(data, "load_assets", roster)
    with pytest.raises(data.DataError, match="Invalid Fantasy price"):
        data.snapshot(
            2026, datetime(2026, 10, 26, tzinfo=timezone.utc), allow_old_prices=True
        )
    assert called == [19]


def test_old_prices_flag_prefers_published_upcoming_feed(monkeypatch):
    previous = data.Weekend(
        2026,
        18,
        "USA",
        18,
        datetime(2026, 10, 24, tzinfo=timezone.utc),
        False,
        True,
        datetime(2026, 10, 25, 20, tzinfo=timezone.utc),
    )
    upcoming = data.Weekend(
        2026,
        19,
        "Mexico",
        19,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
        False,
        False,
    )
    monkeypatch.setattr(data, "season_weekends", lambda _: [previous, upcoming])
    calls = []

    def roster(week, *, require_recent=True):
        calls.append(week)
        return (data.Asset("c", "Team", "CONSTRUCTOR", "t", 50),), datetime(
            2026, 10, 26, tzinfo=timezone.utc
        )

    monkeypatch.setattr(data, "load_assets", roster)
    result, _ = data.snapshot(
        2026, datetime(2026, 10, 26, tzinfo=timezone.utc), allow_old_prices=True
    )
    assert result.provisional is False and result.price_weekend == upcoming
    assert calls == [19, 18]


def test_previous_feed_must_be_updated_after_completed_race(monkeypatch):
    previous = data.Weekend(
        2026,
        18,
        "USA",
        18,
        datetime(2026, 10, 24, tzinfo=timezone.utc),
        False,
        True,
        datetime(2026, 10, 25, 20, tzinfo=timezone.utc),
    )
    upcoming = data.Weekend(
        2026,
        19,
        "Mexico",
        19,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
        False,
        False,
    )
    monkeypatch.setattr(data, "season_weekends", lambda _: [previous, upcoming])

    def roster(week, *, require_recent=True):
        if week == 19:
            raise data.RosterNotPublished("Not available")
        return (), datetime(2026, 10, 25, 19, tzinfo=timezone.utc)

    monkeypatch.setattr(data, "load_assets", roster)
    with pytest.raises(data.DataError, match="not been updated"):
        data.snapshot(
            2026, datetime(2026, 10, 26, tzinfo=timezone.utc), allow_old_prices=True
        )
