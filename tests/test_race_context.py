"""Weather is optional, unit-checked display context, never a forecast feature."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest
import requests

from f1fantasy import race_context as module
from f1fantasy.data import Weekend


NOW = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)


@pytest.fixture
def weekend():
    return Weekend(
        2026,
        19,
        "Mexico City Grand Prix",
        19,
        datetime(2026, 10, 31, 21, tzinfo=timezone.utc),
        False,
        False,
        datetime(2026, 11, 1, 22, tzinfo=timezone.utc),
    )


@pytest.fixture
def payload():
    return {
        "daily_units": {
            "temperature_2m_min": "°C",
            "temperature_2m_max": "°C",
            "precipitation_probability_max": "%",
            "wind_speed_10m_max": "km/h",
        },
        "daily": {
            "time": ["2026-10-31", "2026-11-01"],
            "temperature_2m_min": [11, 12],
            "temperature_2m_max": [24, 25],
            "precipitation_probability_max": [20, 35],
            "wind_speed_10m_max": [14, 18],
        },
    }


def response(monkeypatch, payload):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr(module.requests, "get", lambda *a, **k: Response())


def test_context_has_verified_track_spec_and_explicit_air_units(
    monkeypatch, weekend, payload
):
    response(monkeypatch, payload)
    result = module.race_context(weekend, now=NOW)
    assert result["track_spec"]["length_km"] == 4.304
    assert result["track_spec"]["race_laps"] == 71
    assert result["weather"] == {
        "status": "available",
        "fetched_at": NOW.isoformat(),
        "start_date": "2026-10-31",
        "end_date": "2026-11-01",
        "timezone": "UTC",
        "air_min_c": 11,
        "air_max_c": 25,
        "daily_rain_probability_max": 35,
        "wind_max_kmh": 18,
        "source": "https://open-meteo.com/",
        "license": "CC BY 4.0",
    }


@pytest.mark.parametrize(
    "fault", ["null", "dates", "units", "rain", "wind", "temperature"]
)
def test_malformed_optional_weather_does_not_invent_values(
    monkeypatch, weekend, payload, fault
):
    if fault == "null":
        payload["daily"]["temperature_2m_min"][0] = None
    elif fault == "dates":
        payload["daily"]["time"][0] = "2026-10-30"
    elif fault == "units":
        payload["daily_units"]["temperature_2m_max"] = "°F"
    elif fault == "rain":
        payload["daily"]["precipitation_probability_max"][0] = 101
    elif fault == "wind":
        payload["daily"]["wind_speed_10m_max"][0] = -1
    else:
        payload["daily"]["temperature_2m_min"][0] = 30
    response(monkeypatch, payload)
    result = module.race_context(weekend, now=NOW)
    assert result["weather"] == {"status": "unavailable"}
    assert result["track_spec"]["race_laps"] == 71


def test_weather_outage_is_non_blocking(monkeypatch, weekend):
    def fail(*args, **kwargs):
        raise requests.Timeout("offline")

    monkeypatch.setattr(module.requests, "get", fail)
    assert module.race_context(weekend, now=NOW)["weather"]["status"] == "unavailable"


def test_distant_or_unknown_round_never_requests_guessed_weather(monkeypatch, weekend):
    def fail(*args, **kwargs):
        pytest.fail("No out-of-range weather request")

    monkeypatch.setattr(module.requests, "get", fail)
    distant = replace(
        weekend,
        first_session=NOW + timedelta(days=20),
        last_session=NOW + timedelta(days=21),
    )
    assert (
        module.race_context(distant, now=NOW)["weather"]["status"] == "outside_horizon"
    )
    assert "track_spec" not in module.race_context(
        replace(weekend, season=2027), now=NOW
    )
