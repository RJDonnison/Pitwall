"""Compact FastF1 timing, reliability, tyre and race-regime observations.

Refresh is an explicit offline operation. Forecast publication never downloads
target sessions. Pit-in/out timestamps are never treated as stationary times.
"""

import argparse
from datetime import datetime, timedelta, timezone
import time

import fastf1
import numpy as np
import pandas as pd
import requests

from . import history, public_history
from .data import DataError

VERSION = 2


def finite(value):
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def seconds(value):
    if pd.isna(value):
        return None
    return finite(pd.Timedelta(value).total_seconds())


def cause(status):
    status = str(status).lower()
    if status == "finished" or status.startswith("+"):
        return None
    if "disqual" in status or "excluded" in status:
        return "disqualified"
    if status in {"did not start", "did not qualify", "withdrawn"}:
        return "did_not_start"
    if "collision" in status:
        return "collision"
    if any(word in status for word in ("accident", "spun", "crash")):
        return "driver_error"
    if any(
        word in status
        for word in (
            "engine",
            "gearbox",
            "power",
            "hydraulic",
            "electrical",
            "brake",
            "suspension",
            "transmission",
            "overheat",
            "clutch",
            "oil",
            "water",
            "fuel",
            "mechanical",
            "exhaust",
            "turbo",
            "driveshaft",
        )
    ):
        return "mechanical"
    return "unknown"


def extract(session, kind):
    results = session.results
    laps = getattr(session, "laps", None)
    qualifying = kind in {"Q", "SQ"}
    phases = {}
    for phase in ("Q1", "Q2", "Q3"):
        values = {
            str(r["Abbreviation"]): seconds(r.get(phase)) for _, r in results.iterrows()
        }
        valid = [v for v in values.values() if v is not None and v > 0]
        phases[phase] = (
            {
                tla: 100 * (v / min(valid) - 1)
                for tla, v in values.items()
                if v is not None and v > 0
            }
            if valid
            else {}
        )
    clean = None
    if laps is not None and not laps.empty and "LapTime" in laps:
        mask = laps["LapTime"].notna() & laps["IsAccurate"].fillna(False).astype(bool)
        for field in ("PitInTime", "PitOutTime"):
            mask &= laps[field].isna()
        mask &= laps["TrackStatus"].astype(str).eq("1")
        if "Deleted" in laps:
            mask &= ~laps["Deleted"].fillna(False).astype(bool)
        mask &= laps["LapNumber"] > 1
        clean = laps.loc[mask].copy()
        clean["seconds"] = clean["LapTime"].dt.total_seconds()
        # Compare cars on the same lap and compound: fuel load, track evolution
        # and compound changes must not masquerade as a car-performance margin.
        groups = clean.groupby(["LapNumber", "Compound"])["seconds"]
        reference = groups.transform("median")
        count = groups.transform("count")
        clean["pace_gap_pct"] = np.where(
            count >= 3, 100 * (clean["seconds"] / reference - 1), np.nan
        )
    weather = getattr(session, "weather_data", None)
    wet = None
    if weather is not None and not weather.empty and "Rainfall" in weather:
        wet = float(weather["Rainfall"].fillna(False).astype(bool).mean())
    compounds = (
        set(laps["Compound"].dropna()) if laps is not None and not laps.empty else set()
    )
    wet_tyres = bool(compounds & {"INTERMEDIATE", "WET"})
    dry_tyres = bool(compounds & {"SOFT", "MEDIUM", "HARD"})
    regime = (
        "mixed"
        if wet_tyres and dry_tyres
        else "wet"
        if wet_tyres or (wet is not None and wet > 0.5)
        else "dry"
        if wet is not None
        else "unknown"
    )
    status = (
        laps["TrackStatus"].astype(str)
        if laps is not None and not laps.empty
        else pd.Series([], dtype=str)
    )
    summary = {
        "regime": regime,
        "rain_fraction": wet,
        "safety_car": bool(status.str.contains("4|6|7").any()),
        "red_flag": bool(status.str.contains("5").any()),
    }
    rows = []
    for _, r in results.iterrows():
        tla = str(r["Abbreviation"])
        row = {
            "tla": tla,
            "position": finite(r.get("Position")),
            "classified": finite(r.get("ClassifiedPosition")) is not None,
            "points": finite(r.get("Points")),
            "team_name": str(r.get("TeamName", "")),
            "qualified": finite(r.get("Position")) is not None
            and str(r.get("Status", "")).lower()
            not in {"disqualified", "did not qualify", "did not start"},
            "grid": finite(r.get("GridPosition")),
            "status": str(r.get("Status", "")),
            "retirement_cause": cause(r.get("Status", "")),
            "laps": finite(r.get("Laps")),
            "retirement_lap": finite(r.get("Laps")) + 1
            if cause(r.get("Status", "")) is not None
            and finite(r.get("Laps")) is not None
            else None,
            "qualifying_gaps_pct": {p: v[tla] for p, v in phases.items() if tla in v},
        }
        dl = clean[clean["Driver"] == tla] if clean is not None else None
        row["pace_samples"] = (
            int(dl["pace_gap_pct"].notna().sum()) if dl is not None else 0
        )
        row["pace_gap_pct"] = (
            phases["Q1"].get(tla)
            if qualifying
            else finite(dl["pace_gap_pct"].median())
            if dl is not None and row["pace_samples"] >= 3
            else None
        )
        if dl is not None and not dl.empty:
            best = dl.loc[dl["seconds"].idxmin()]
            row.update(
                best_lap_seconds=finite(best["seconds"]),
                best_lap_tyre_age=finite(best.get("TyreLife")),
                best_lap_number=finite(best.get("LapNumber")),
                median_tyre_age=finite(dl["TyreLife"].median()),
            )
        driver_laps = (
            laps[laps["Driver"] == tla] if laps is not None and not laps.empty else None
        )
        row["pit_stops"] = (
            int(driver_laps["PitInTime"].notna().sum())
            if driver_laps is not None
            else None
        )
        row["first_lap_incident"] = (
            row["retirement_cause"] in {"collision", "driver_error"}
            and row["laps"] is not None
            and row["laps"] <= 1
        )
        rows.append(row)
    return rows, summary


def refresh(document, start_season, season, cutoff):
    history.configure_cache()
    for year in range(start_season, season + 1):
        schedule = public_history.schedule(year)
        for _, event in schedule.iterrows():
            end = public_history.date(event["race_start"]) + timedelta(hours=6)
            if end >= cutoff:
                continue
            number = int(event["RoundNumber"])
            old = public_history.racing_record(year, number, cutoff)
            if old is not None and old.get("timing_schema") == VERSION:
                for rows in old["sessions"].values():
                    for row in rows:
                        row["retirement_cause"] = cause(row["status"])
                        row["retirement_lap"] = (
                            row["laps"] + 1
                            if row["retirement_cause"] is not None
                            and row["laps"] is not None
                            else None
                        )
                continue
            record = {
                "season": year,
                "round": number,
                "end": end.isoformat(),
                "race_start_utc": event["race_start"],
                "location": event["Location"],
                "sessions": {},
                "session_context": {},
                "timing_schema": VERSION,
            }
            fmt = str(event["EventFormat"])
            kinds = ["Q", "R"] + (["S", "SQ"] if "sprint" in fmt else [])
            for kind in kinds:
                identifier = "SS" if kind == "SQ" and fmt == "sprint_shootout" else kind
                session = fastf1.get_session(year, number, identifier)
                session.load(laps=True, telemetry=False, weather=True, messages=True)
                if session.results is None or session.results.empty:
                    raise DataError(
                        f"Missing historical results {year}/{number}/{kind}"
                    )
                laps = session.laps
                if (
                    laps is not None
                    and not laps.empty
                    and laps["LapStartDate"].notna().any()
                ):
                    actual = pd.Timestamp(laps["LapStartDate"].max())
                    if actual.tzinfo is None:
                        actual = actual.tz_localize("UTC")
                    actual = actual.to_pydatetime() + timedelta(hours=1)
                    if actual >= cutoff:
                        raise DataError("Timing session overlaps the historical cutoff")
                    record["end"] = max(
                        public_history.date(record["end"]), actual
                    ).isoformat()
                rows, context = extract(session, kind)
                record["sessions"][kind] = rows
                record["session_context"][kind] = context
                if kind in {"R", "S"} and laps is not None and not laps.empty:
                    valid = laps["LapTime"].notna() & ~laps["Deleted"].fillna(
                        False
                    ).astype(bool)
                    if valid.any():
                        record[
                            "fastest_lap" if kind == "R" else "sprint_fastest_lap"
                        ] = str(laps.loc[laps.loc[valid, "LapTime"].idxmin(), "Driver"])
            public_history.save_racing(record)
            print(f"Archived timing {year}/{number}", flush=True)


def refresh_stops(document, cutoff):
    """OpenF1 explicitly separates stop_duration from lane_duration (2024 US+)."""
    last_request = 0.0

    def get(endpoint, **params):
        nonlocal last_request
        time.sleep(max(0, 2.1 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        response = requests.get(
            f"https://api.openf1.org/v1/{endpoint}", params=params, timeout=40
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise DataError("OpenF1 did not return historical rows")
        return data

    archived = {
        (r["season"], r["round"]): r for r in document.get("stationary_stops", [])
    }
    for year in sorted({r["season"] for r in document["racing"]}):
        sessions = get("sessions", year=year, session_name="Race")
        for record in sorted(
            (r for r in document["racing"] if r["season"] == year),
            key=lambda r: r["round"],
        ):
            key = year, record["round"]
            if key in archived or public_history.date(record["end"]) >= cutoff:
                continue
            start = public_history.date(record["race_start_utc"])
            matches = [
                s
                for s in sessions
                if abs((public_history.date(s["date_start"]) - start).total_seconds())
                < 1800
                and public_history.date(s["date_end"]) < cutoff
            ]
            if len(matches) != 1:
                continue
            session = matches[0]
            drivers = {
                int(d["driver_number"]): d
                for d in get("drivers", session_key=session["session_key"])
            }
            stops = []
            for stop in get("pit", session_key=session["session_key"]):
                duration = finite(stop.get("stop_duration"))
                driver = drivers.get(int(stop["driver_number"]))
                if (
                    duration is None
                    or duration <= 0
                    or not driver
                    or public_history.date(stop["date"]) >= cutoff
                ):
                    continue
                stops.append(
                    {
                        "team_name": driver["team_name"],
                        "tla": driver["name_acronym"],
                        "seconds": duration,
                        "date": stop["date"],
                        "lap": stop["lap_number"],
                    }
                )
            if stops:
                archived[key] = {
                    "season": year,
                    "round": record["round"],
                    "end": record["end"],
                    "session_key": session["session_key"],
                    "source": "https://openf1.org/docs/#pit",
                    "stops": stops,
                }
                print(
                    f"Archived {len(stops)} stationary stops {year}/{record['round']}",
                    flush=True,
                )
    document["stationary_stops"] = [archived[k] for k in sorted(archived)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", default=public_history.DEFAULT)
    parser.add_argument(
        "--start-season", type=int, default=datetime.now(timezone.utc).year - 2
    )
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--stationary-stops", action="store_true")
    args = parser.parse_args(argv)
    with public_history.repository(args.history, update=True) as doc:
        cutoff = datetime.now(timezone.utc)
        refresh(doc, args.start_season, args.season, cutoff)
        if args.stationary_stops:
            refresh_stops(doc, cutoff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
