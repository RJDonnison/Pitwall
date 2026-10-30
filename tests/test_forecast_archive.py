from copy import deepcopy
from datetime import datetime, timezone

from f1fantasy import forecast_archive, weather_model
from f1fantasy.data import Asset, Weekend


def publication():
    return dict(
        season=2026,
        generated_at="2026-10-01T10:00:00+00:00",
        forecast_cutoff="2026-10-01T10:00:00+00:00",
        model={"version": "test"},
        assets=[],
        rounds=[
            dict(
                round=20,
                gameday_id=20,
                sprint=False,
                first_session_utc="2026-10-02T10:00:00+00:00",
                forecasts={"1": [2, 0, 10]},
            )
        ],
    )


def test_first_snapshot_is_immutable_and_post_start_is_excluded():
    archive = {"schema": 1, "forecasts": []}
    p = publication()
    forecast_archive.capture(archive, p)
    p = deepcopy(p)
    p["rounds"][0]["forecasts"]["1"] = [99, 0, 99]
    forecast_archive.capture(archive, p)
    assert archive["forecasts"][0]["forecasts"]["1"] == [2, 0, 10]
    p["rounds"][0]["round"] = 21
    p["generated_at"] = "2026-10-03T10:00:00+00:00"
    forecast_archive.capture(archive, p)
    assert len(archive["forecasts"]) == 1


def test_settlement_needs_finalized_matching_year_and_round():
    archive = {"schema": 1, "forecasts": []}
    forecast_archive.capture(archive, publication())
    end = "2026-10-04T20:00:00+00:00"
    d = dict(
        fantasy_events={"20": end},
        fantasy={"20": [dict(PlayerId=1, QualifyingPoints=3, GamedayPoints=18)]},
        racing=[dict(season=2026, round=20, end=end)],
    )
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert forecast_archive.settled(archive, d, now)[0]["actual"]["1"] == [3, 0, 15]
    d["racing"][0]["season"] = 2025
    assert forecast_archive.settled(archive, d, now) == []


def test_weather_thresholds_and_temporal_gate():
    assert [weather_model.classify(v) for v in (0, 29, 30, 69, 70, 100)] == [
        "dry",
        "dry",
        "changeable",
        "changeable",
        "wet",
        "wet",
    ]
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    weekend = Weekend(
        2026, 20, "Test", 20, datetime(2026, 10, 2, tzinfo=timezone.utc), False, False
    )
    a = Asset("1", "Driver", "DRIVER", "1", 100)
    weather = dict(
        status="available",
        fetched_at="2026-10-01T00:00:00+00:00",
        daily_rain_probability_max=80,
    )
    candidate = weather_model.candidate(
        [a], weekend, {"1": [2, 0, 10]}, weather, {}, now
    )
    assert candidate["condition"] == "wet" and not candidate["applied"]
    assert candidate["forecasts"]["1"] == [2, 0, 10]
    weather["fetched_at"] = "2026-10-03T00:00:00+00:00"
    assert (
        weather_model.candidate([a], weekend, {"1": [2, 0, 10]}, weather, {}, now)[
            "status"
        ]
        == "unavailable"
    )
