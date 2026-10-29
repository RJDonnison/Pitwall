"""Optional, sourced race-weekend context; never an optimizer input."""

from datetime import datetime, timedelta, timezone
import math
import unicodedata

import requests


# Published 2026 Formula 1 circuit specifications, checked 2026-10-29.
# Coordinates identify the circuit, not the weather model's selected grid cell.
TRACKS = {
    "mexico": (4.304, 71, 305.354, 19.405, -99.092, "mexico"),
    "sao paulo": (4.309, 71, 305.879, -23.703, -46.699, "brazil"),
    "las vegas": (6.201, 50, 309.958, 36.110, -115.162, "las-vegas"),
    "qatar": (5.419, 57, 308.611, 25.490, 51.454, "qatar"),
    "abu dhabi": (5.281, 58, 306.188, 24.468, 54.604, "united-arab-emirates"),
}


def race_context(weekend, *, now=None):
    """Attach optional public weather; missing/out-of-range forecasts stay missing."""
    now = now or datetime.now(timezone.utc)
    name = "".join(
        c
        for c in unicodedata.normalize("NFD", weekend.name.lower())
        if not unicodedata.combining(c)
    )
    track = next((v for k, v in TRACKS.items() if k in name), None)
    result = {"weather": {"status": "unavailable"}}
    if track is None or weekend.season != 2026:
        return result
    length, laps, distance, latitude, longitude, slug = track
    result["track_spec"] = {
        "length_km": length,
        "race_laps": laps,
        "race_distance_km": distance,
        "season": 2026,
        "checked_at": "2026-10-29",
        "source": f"https://www.formula1.com/en/racing/2026/{slug}/circuit",
    }
    start = weekend.first_session.astimezone(timezone.utc).date()
    end = (
        (weekend.last_session or weekend.first_session).astimezone(timezone.utc).date()
    )
    if start < now.date() or end > now.date() + timedelta(days=15):
        result["weather"]["status"] = "outside_horizon"
        return result
    fields = [
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_probability_max",
        "wind_speed_10m_max",
    ]
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(fields),
                "timezone": "UTC",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        daily, units = payload["daily"], payload["daily_units"]
        days = [
            (start + timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)
        ]
        if daily["time"] != days or [units[f] for f in fields] != [
            "°C",
            "°C",
            "%",
            "km/h",
        ]:
            raise ValueError("Weather date or unit mismatch")
        for field in fields:
            if len(daily[field]) != len(days) or any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in daily[field]
            ):
                raise ValueError("Incomplete weather")
        low, high, rain, wind = [daily[f] for f in fields]
        if (
            any(lo > hi for lo, hi in zip(low, high))
            or any(not 0 <= p <= 100 for p in rain)
            or any(v < 0 for v in wind)
        ):
            raise ValueError("Invalid weather range")
        result["weather"] = {
            "status": "available",
            "fetched_at": now.isoformat(),
            "start_date": days[0],
            "end_date": days[-1],
            "timezone": "UTC",
            "air_min_c": min(low),
            "air_max_c": max(high),
            "daily_rain_probability_max": max(rain),
            "wind_max_kmh": max(wind),
            "source": "https://open-meteo.com/",
            "license": "CC BY 4.0",
        }
    except (requests.RequestException, KeyError, TypeError, ValueError):
        # Optional context must not prevent a verified Fantasy publication.
        pass
    return result
