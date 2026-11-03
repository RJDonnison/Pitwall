"""Sourced Predict facts and compact completed-race observations.

Collection is an explicit history-refresh operation. Forecasts only read the
archive, and filter racing observations and winners at their own cutoff.
"""

from datetime import datetime, timedelta
import json
import time

import pandas as pd
import requests

from . import public_history
from .data import DataError
from .session_laps import loaded

JOLPICA = "https://api.jolpi.ca/ergast/f1/"
OBSERVATION_VERSION = 1


def document():
    source = public_history.current()
    if source:
        return source["document"]
    try:
        return json.loads(public_history.DEFAULT.read_text())
    except (OSError, ValueError):
        return {}


def race_observation(session):
    messages = loaded(session, "race_control_messages")
    result = {}
    if messages is not None and not messages.empty:
        # A deployment, not each lap behind the SC or its "ending" message,
        # constitutes one intervention. A VSC-to-SC transition is two deployments.
        safety, red, active, red_active = [], 0, None, False
        for _, row in messages.iterrows():
            text = str(row.get("Message", "")).upper()
            flag = str(row.get("Flag", "")).upper()
            scope = str(row.get("Scope", "")).lower()
            lap = row.get("Lap")
            if "SAFETY CAR DEPLOYED" in text:
                mode = "VSC" if "VIRTUAL" in text else "SC"
                if mode != active:
                    safety.append(
                        int(lap) if pd.notna(lap) and float(lap) >= 1 else None
                    )
                active = mode
            elif (
                "SAFETY CAR IN THIS LAP" in text or "VIRTUAL SAFETY CAR ENDING" in text
            ):
                active = None
            elif flag == "GREEN" and scope == "track":
                active, red_active = None, False
            if flag == "RED" and scope == "track":
                if not red_active and pd.notna(lap) and float(lap) >= 1:
                    red += 1
                red_active = True
        result.update(safety_laps=safety, red_flags=red)
    results = loaded(session, "results")
    if results is not None and not results.empty and "Laps" in results:
        laps = pd.to_numeric(results["Laps"], errors="coerce")
        if laps.notna().all():
            result["all_complete_first_lap"] = bool((laps >= 1).all())
    return result


def refresh_observations(document, cutoff):
    """Backfill only completed races; do not replace the racing model's inputs."""
    import fastf1

    from .history import configure_cache

    configure_cache()
    existing = {(r["season"], r["round"]): r for r in document.get("predict_races", [])}
    for record in document["racing"]:
        key = record["season"], record["round"]
        if (
            existing.get(key, {}).get("version") == OBSERVATION_VERSION
            or public_history.date(record["end"]) >= cutoff
        ):
            continue
        session = fastf1.get_session(*key, "R")
        session.load(laps=False, telemetry=False, weather=False, messages=True)
        observed = race_observation(session)
        if "safety_laps" not in observed:
            continue  # Missing messages are not a race with zero interventions.
        existing[key] = {
            "version": OBSERVATION_VERSION,
            "season": key[0],
            "round": key[1],
            "end": record["end"],
            "source": "FastF1 race-control messages and official result laps",
            **observed,
        }
        print(f"Archived Predict race control {key[0]}/{key[1]}", flush=True)
    document["predict_races"] = [existing[k] for k in sorted(existing)]


def refresh_facts(document, season, cutoff):
    """Collect complete GP-winner history and sourced sporting nationalities."""

    def get(path, offset=0):
        response = requests.get(
            JOLPICA + path, params={"limit": 100, "offset": offset}, timeout=40
        )
        response.raise_for_status()
        body = response.json()["MRData"]
        if int(body["offset"]) != offset:
            raise DataError("Jolpica pagination offset does not match the request")
        return body

    winners, offset, total = [], 0, None
    while total is None or offset < total:
        body = get("results/1.json", offset)
        if total is not None and total != int(body["total"]):
            raise DataError("Grand Prix winner archive changed during pagination")
        total = int(body["total"])
        races = body["RaceTable"]["Races"]
        count = sum(len(r["Results"]) for r in races)
        if not count:
            raise DataError("Incomplete Grand Prix winner archive")
        for race in races:
            # A missing start time receives a conservative next-day boundary.
            start = datetime.fromisoformat(
                race["date"]
                + "T"
                + race.get("time", "18:00:00Z").replace("Z", "+00:00")
            )
            end = start + timedelta(hours=6)
            if end >= cutoff:
                continue
            for result in race["Results"]:
                driver = result["Driver"]
                if result["position"] != "1":
                    raise DataError("Grand Prix winner source returned a non-winner")
                winners.append(
                    {
                        "meeting": race["raceName"],
                        "end": end.isoformat(),
                        "driver_name": driver["givenName"] + " " + driver["familyName"],
                        "tla": driver.get("code", ""),
                    }
                )
        offset += count
        time.sleep(1.1)
    drivers = {}
    for year in range(season - 2, season + 1):
        body = get(f"{year}/drivers.json")
        rows = body["DriverTable"]["Drivers"]
        if len(rows) != int(body["total"]):
            raise DataError("Incomplete sporting nationality archive")
        for row in rows:
            if row.get("code") and row.get("nationality"):
                drivers[row["driverId"]] = {
                    "name": row["givenName"] + " " + row["familyName"],
                    "tla": row["code"],
                    "nationality": row["nationality"],
                }
        time.sleep(1.1)
    document["predict_facts"] = {
        "source": JOLPICA,
        "checked_at": cutoff.isoformat(),
        "winner_history_complete": True,
        "winners": winners,
        "drivers": list(drivers.values()),
    }
