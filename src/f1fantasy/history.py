"""Persistent, date-stamped FastF1 telemetry features for completed sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import fastf1
import numpy as np
import pandas as pd

from .data import DataError

SCHEMA = 1
DEFAULT_CACHE = Path(".f1fantasy/cache")


def configure_cache(root: Path = DEFAULT_CACHE) -> None:
    path = root / "fastf1"
    path.mkdir(parents=True, exist_ok=True)
    if hasattr(fastf1.Cache, "configure"):
        fastf1.Cache.configure(cache_dir=str(path))
    else:
        fastf1.Cache.enable_cache(str(path))


def feature_path(
    year: int, round_number: int, identifier: int, root: Path = DEFAULT_CACHE
) -> Path:
    return (
        root
        / "features"
        / f"v{SCHEMA}"
        / str(year)
        / f"{round_number:02d}-{identifier}.json"
    )


def load_features(
    year: int,
    round_number: int,
    identifier: int,
    cutoff: datetime,
    root: Path = DEFAULT_CACHE,
) -> dict[str, Any] | None:
    path = feature_path(year, round_number, identifier, root)
    if not path.exists():
        return None
    try:
        result = json.loads(path.read_text())
        date = datetime.fromisoformat(result["completed_at"])
        if (
            result["schema"] != SCHEMA
            or result["year"] != year
            or result["round"] != round_number
            or result["session_number"] != identifier
            or not isinstance(result["drivers"], dict)
            or not isinstance(result["track"], dict)
            or date.tzinfo is None
            or date >= cutoff
        ):
            raise DataError(f"Invalid or future telemetry cache entry: {path}")
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DataError(f"Cannot verify telemetry cache {path}: {exc}") from exc


def _clean_laps(session: Any) -> Any:
    laps = session.laps
    if laps is None or laps.empty:
        raise DataError("Session has no completed laps")
    mask = laps["LapTime"].notna() & laps["IsAccurate"].fillna(False)
    for field in ("PitInTime", "PitOutTime"):
        if field in laps:
            mask &= laps[field].isna()
    if "TrackStatus" in laps:
        mask &= laps["TrackStatus"].astype(str).eq("1")
    return laps[mask]


def _car_features(lap: Any) -> dict[str, float] | None:
    try:
        car = lap.get_car_data().add_distance()
        if len(car) < 30:
            return None
        distance = np.asarray(car["Distance"], dtype=float)
        speed = np.asarray(car["Speed"], dtype=float)
        brake = np.asarray(car["Brake"], dtype=float)
        throttle = np.asarray(car["Throttle"], dtype=float)
        weights = np.diff(distance, prepend=distance[0])
        valid = (
            np.isfinite(speed)
            & np.isfinite(weights)
            & np.isfinite(brake)
            & np.isfinite(throttle)
            & (weights >= 0)
        )
        if valid.sum() < 30 or weights[valid].sum() < 1000:
            return None
        weights = weights[valid]
        speed, brake, throttle = speed[valid], brake[valid], throttle[valid]
        return {
            "length_m": float(distance[-1]),
            "speed_kmh": float(np.average(speed, weights=weights)),
            "straight_fraction": float(np.average(speed >= 250, weights=weights)),
            "slow_fraction": float(np.average(speed < 130, weights=weights)),
            "braking_fraction": float(np.average(brake > 0, weights=weights)),
            "full_throttle_fraction": float(
                np.average(throttle >= 95, weights=weights)
            ),
        }
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def extract_features(
    session: Any,
    *,
    year: int,
    round_number: int,
    identifier: int,
    completed_at: datetime,
) -> dict[str, Any]:
    clean = _clean_laps(session)
    drivers: dict[str, dict[str, Any]] = {}
    telemetry = []
    for tla in sorted(set(clean["Driver"].dropna())):
        driver_laps = clean[clean["Driver"] == tla]
        best = driver_laps.loc[driver_laps["LapTime"].idxmin()]
        pace = float(median(driver_laps["LapTime"].dt.total_seconds()))
        features = _car_features(best)
        if features is None:
            continue
        team = str(best["Team"])
        drivers[str(tla)] = {"team": team, "pace_seconds": pace, **features}
        telemetry.append(features)
    if not telemetry:
        raise DataError("No valid car telemetry from accurate green-flag laps")
    for driver in drivers.values():
        mates = [
            d["pace_seconds"]
            for d in drivers.values()
            if d["team"] == driver["team"] and d is not driver
        ]
        driver["teammate_gap_seconds"] = (
            (driver["pace_seconds"] - median(mates)) if mates else None
        )
    names = (
        "length_m",
        "speed_kmh",
        "straight_fraction",
        "slow_fraction",
        "braking_fraction",
        "full_throttle_fraction",
    )
    track = {key: float(median(row[key] for row in telemetry)) for key in names}
    weather = getattr(session, "weather_data", None)
    if weather is not None and not weather.empty:
        if "TrackTemp" in weather:
            temperature = float(weather["TrackTemp"].median())
            if np.isfinite(temperature):
                track["track_temp_c"] = temperature
        if "Rainfall" in weather:
            track["rainfall"] = bool(weather["Rainfall"].fillna(False).any())
    return {
        "schema": SCHEMA,
        "year": year,
        "round": round_number,
        "session_number": identifier,
        "session": session.name,
        "location": str(session.event["Location"]),
        "completed_at": completed_at.isoformat(),
        "track": track,
        "drivers": drivers,
    }


def preload(
    seasons: int = 3,
    *,
    root: Path = DEFAULT_CACHE,
    refresh: bool = False,
    now: datetime | None = None,
) -> tuple[int, int, list[str]]:
    """Download and summarize all *completed* sessions; safely resume existing work."""
    if seasons not in (1, 2, 3):
        raise ValueError("--seasons must be 1, 2 or 3")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DataError("Preload cutoff must include a timezone")
    configure_cache(root)
    stored = skipped = 0
    gaps: list[str] = []
    for year in range(now.year - seasons + 1, now.year + 1):
        try:
            schedule = fastf1.get_event_schedule(year)
        except Exception as exc:
            gaps.append(f"{year} schedule: {exc}")
            continue
        for _, listing in schedule.iterrows():
            round_number = int(listing["RoundNumber"])
            if round_number < 1:
                continue
            event = fastf1.get_event(year, round_number)
            for identifier in range(1, 6):
                name = event.get(f"Session{identifier}")
                if not isinstance(name, str) or not name.strip():
                    continue
                date = event.get_session_date(identifier, utc=True)
                if date is None or pd.isna(date):
                    continue
                completed_at = date.to_pydatetime().replace(
                    tzinfo=timezone.utc
                ) + timedelta(hours=5)
                if completed_at >= now:
                    continue
                path = feature_path(year, round_number, identifier, root)
                if path.exists() and not refresh:
                    load_features(year, round_number, identifier, now, root)
                    skipped += 1
                    continue
                try:
                    session = fastf1.get_session(year, round_number, identifier)
                    session.load(
                        laps=True, telemetry=True, weather=True, messages=False
                    )
                    data = extract_features(
                        session,
                        year=year,
                        round_number=round_number,
                        identifier=identifier,
                        completed_at=completed_at,
                    )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(data, allow_nan=False))
                    temporary.replace(path)
                    stored += 1
                except Exception as exc:
                    gaps.append(f"{year} round {round_number} {name}: {exc}")
    return stored, skipped, gaps


def cache_status(root: Path = DEFAULT_CACHE) -> dict[int, int]:
    directory = root / "features" / f"v{SCHEMA}"
    if not directory.exists():
        return {}
    return {
        int(folder.name): len(list(folder.glob("*.json")))
        for folder in directory.iterdir()
        if folder.is_dir() and folder.name.isdigit()
    }
