from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from f1fantasy import history
from f1fantasy.data import DataError


def test_car_telemetry_uses_distance_weighted_track_features():
    class Car:
        def __init__(self):
            self.values = {
                "Distance": np.linspace(0, 3000, 60),
                "Speed": np.array([100] * 30 + [300] * 30),
                "Brake": np.array([1] * 30 + [0] * 30),
                "Throttle": np.array([0] * 30 + [100] * 30),
            }

        def add_distance(self):
            return self

        def __len__(self):
            return 60

        def __getitem__(self, key):
            return self.values[key]

    class Lap:
        def get_car_data(self):
            return Car()

    result = history._car_features(Lap())
    assert result is not None and result["length_m"] == 3000
    assert 0.4 < result["straight_fraction"] < 0.6
    assert 0.4 < result["braking_fraction"] < 0.6


def test_extract_session_features_and_teammate_normalization(monkeypatch):
    class Event(dict):
        pass

    class Session:
        name = "Qualifying"
        event = Event(Location="Monaco")
        weather_data = pd.DataFrame({"TrackTemp": [29.0], "Rainfall": [False]})
        laps = pd.DataFrame(
            [
                {
                    "Driver": "AAA",
                    "Team": "Team",
                    "LapTime": timedelta(seconds=71),
                    "IsAccurate": True,
                    "TrackStatus": "1",
                },
                {
                    "Driver": "BBB",
                    "Team": "Team",
                    "LapTime": timedelta(seconds=72),
                    "IsAccurate": True,
                    "TrackStatus": "1",
                },
                {
                    "Driver": "CCC",
                    "Team": "Other",
                    "LapTime": timedelta(seconds=55),
                    "IsAccurate": False,
                    "TrackStatus": "1",
                },
            ]
        )

    monkeypatch.setattr(
        history,
        "_car_features",
        lambda lap: {
            "length_m": 3300.0,
            "speed_kmh": 170.0,
            "straight_fraction": 0.1,
            "slow_fraction": 0.5,
            "braking_fraction": 0.3,
            "full_throttle_fraction": 0.2,
        },
    )
    result = history.extract_features(
        Session(),
        year=2026,
        round_number=8,
        identifier=4,
        completed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert result["track"]["slow_fraction"] == 0.5
    assert result["drivers"]["AAA"]["teammate_gap_seconds"] == -1
    assert "CCC" not in result["drivers"]


def test_preload_resumes_and_refuses_future_features(tmp_path, monkeypatch):
    class Event(dict):
        def get_session_date(self, identifier, utc=False):
            return (
                pd.Timestamp("2026-01-10")
                if identifier == 1
                else pd.Timestamp("2026-12-10")
            )

    event = Event(
        RoundNumber=1, Location="Monaco", Session1="Qualifying", Session2="Race"
    )
    monkeypatch.setattr(
        history.fastf1.Cache, "configure", lambda **_kwargs: None, raising=False
    )
    monkeypatch.setattr(
        history.fastf1,
        "get_event_schedule",
        lambda _: pd.DataFrame({"RoundNumber": [1]}),
    )
    monkeypatch.setattr(history.fastf1, "get_event", lambda *_: event)

    class Session:
        name = "Qualifying"
        api_path = "/static/2026/Monaco/Qualifying/"

        def load(self, **kwargs):
            calls.append(kwargs)
            cache = tmp_path / "fastf1/2026/Monaco/Qualifying"
            cache.mkdir(parents=True, exist_ok=True)
            for name in ("car_data", "position_data", "driver_info"):
                (cache / f"{name}.ff1pkl").write_bytes(b"cached")

    calls = []
    monkeypatch.setattr(history.fastf1, "get_session", lambda *_: Session())
    monkeypatch.setattr(
        history,
        "extract_features",
        lambda *_args, **kw: {
            "schema": history.SCHEMA,
            "year": kw["year"],
            "round": kw["round_number"],
            "session_number": kw["identifier"],
            "completed_at": kw["completed_at"].isoformat(),
            "track": {"slow_fraction": 0.3},
            "drivers": {"AAA": {"pace_seconds": 70}},
        },
    )
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert history.preload(1, root=tmp_path, now=now) == (1, 0, [])
    cache = tmp_path / "fastf1/2026/Monaco/Qualifying"
    assert not (cache / "car_data.ff1pkl").exists()
    assert not (cache / "position_data.ff1pkl").exists()
    assert (cache / "driver_info.ff1pkl").read_bytes() == b"cached"
    assert calls == [
        {"laps": True, "telemetry": True, "weather": True, "messages": True}
    ]
    assert history.preload(1, root=tmp_path, now=now) == (0, 1, [])
    assert history.cache_status(tmp_path) == {2026: 1}
    assert history.load_features(2026, 1, 1, now, tmp_path) is not None
    with pytest.raises(DataError, match="future"):
        history.load_features(
            2026, 1, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), tmp_path
        )


def test_configure_cache_disables_raw_http_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        history.fastf1.Cache, "configure", lambda **kwargs: calls.append(kwargs)
    )
    history.configure_cache(tmp_path)
    assert calls == [
        {"cache_dir": str(tmp_path / "fastf1"), "use_requests_cache": False}
    ]


def test_compaction_refuses_outside_cache(tmp_path):
    class Session:
        api_path = "/static/2026/../outside/"

    with pytest.raises(DataError, match="Cannot locate"):
        history._compact_session(tmp_path, Session())


def test_clean_laps_excludes_deleted_laps():
    class Session:
        laps = pd.DataFrame(
            [
                {
                    "LapTime": timedelta(seconds=70),
                    "IsAccurate": True,
                    "TrackStatus": "1",
                    "Deleted": True,
                },
                {
                    "LapTime": timedelta(seconds=71),
                    "IsAccurate": True,
                    "TrackStatus": "1",
                    "Deleted": False,
                },
            ]
        )

    assert len(history._clean_laps(Session())) == 1
