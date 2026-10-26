from datetime import datetime, timezone

from f1fantasy import telemetry_model
from f1fantasy.data import Asset, Weekend


def test_similar_track_teammate_form_adjusts_sprint_and_race(monkeypatch):
    assets = (
        Asset("a", "A", "DRIVER", "team", 50, "AAA"),
        Asset("b", "B", "DRIVER", "team", 50, "BBB"),
        Asset("c", "Team", "CONSTRUCTOR", "team", 50),
    )
    target = Weekend(
        2026, 4, "Monaco", 4, datetime(2026, 5, 24, tzinfo=timezone.utc), True, False
    )

    def record(location, speed, year, a_gap):
        return {
            "year": year,
            "location": location,
            "session": "Qualifying",
            "track": {
                "speed_kmh": speed,
                "straight_fraction": 0.1 if speed < 200 else 0.7,
                "slow_fraction": 0.5 if speed < 200 else 0.1,
                "braking_fraction": 0.3 if speed < 200 else 0.05,
            },
            "drivers": {
                "AAA": {"teammate_gap_seconds": a_gap, "pace_seconds": 70},
                "BBB": {"teammate_gap_seconds": -a_gap, "pace_seconds": 70},
            },
        }

    records = [
        record("Monaco", 175, 2025, -1),
        record("Singapore", 178, 2026, -1),
        record("Monza", 260, 2026, 1),
        record("Baku", 270, 2025, 1),
    ]
    monkeypatch.setattr(
        telemetry_model, "historical_features", lambda cutoff, root: records
    )
    monkeypatch.setattr(
        telemetry_model.fastf1, "get_event", lambda *_: {"Location": "Monaco"}
    )
    result = telemetry_model.adjustments(assets, [target])
    assert result[0, "a"][0] > 0 and result[0, "a"][1] > 0 and result[0, "a"][2] > 0
    assert result[0, "b"][2] < 0
    assert (0, "c") not in result


def test_without_prior_visit_telemetry_model_keeps_baseline(monkeypatch):
    target = Weekend(
        2026,
        4,
        "New circuit",
        4,
        datetime(2026, 5, 24, tzinfo=timezone.utc),
        False,
        False,
    )
    monkeypatch.setattr(telemetry_model, "historical_features", lambda cutoff, root: [])
    assert telemetry_model.adjustments((), [target]) == {}
