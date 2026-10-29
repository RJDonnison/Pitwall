"""Versioned public summaries for deployment, separate from live market data.

Only explicit website/export contexts use this source. Ordinary CLI commands
retain their existing FastF1 behavior. Read mode never downloads missing history.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from pathlib import Path

import fastf1
import pandas as pd

from .data import DataError

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "history.json"
_source = ContextVar("public_history", default=None)


def current():
    return _source.get()


def date(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise DataError("Public history requires timezone-bearing dates")
    return result


@contextmanager
def repository(path=DEFAULT, *, update=False):
    path = Path(path)
    try:
        document = json.loads(path.read_text()) if path.exists() else None
        if document is None and update:
            document = {
                "schema": 1,
                "events": {},
                "scores": {},
                "fantasy": {},
                "fantasy_events": {},
                "racing": [],
                "features": [],
            }
        if not isinstance(document, dict) or document.get("schema") != 1:
            raise DataError(
                "Public history is missing or unsupported; run the history updater"
            )
        for name in ("events", "scores", "fantasy", "fantasy_events"):
            if not isinstance(document.get(name), dict):
                raise DataError(f"Malformed public history collection: {name}")
        for name in ("racing", "features"):
            if not isinstance(document.get(name), list):
                raise DataError(f"Malformed public history collection: {name}")
        token = _source.set({"document": document, "update": update})
        try:
            yield document
        finally:
            _source.reset(token)
        if update:
            # Failed refreshes leave the previous committed dataset intact.
            document["updated_at"] = datetime.now(timezone.utc).isoformat()
            encoded = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(encoded)
            temporary.replace(path)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(f"Cannot verify public history: {exc}") from exc


class Event(dict):
    def get_session_date(self, session, *, utc=True):
        if session != "Race":
            raise DataError("Only the verified race date is archived")
        return pd.Timestamp(self["race_start"])


def event(year, number):
    source = current()
    if source is None:
        return fastf1.get_event(year, number)
    if isinstance(number, str):
        if source["update"]:
            number = int(fastf1.get_event(year, number)["RoundNumber"])
        else:
            matches = [
                r["RoundNumber"]
                for key, r in source["document"]["events"].items()
                if key.startswith(f"{year}/") and r["EventName"] == number
            ]
            if len(matches) != 1:
                raise DataError(f"Cannot match public history event {year}/{number}")
            number = matches[0]
    key = f"{year}/{number}"
    if source["update"]:
        raw = fastf1.get_event(year, number)
        race = pd.Timestamp(raw.get_session_date("Race", utc=True))
        if pd.isna(race):
            raise DataError(f"Public calendar has no race date: {key}")
        # FastF1's utc=True field is documented UTC even on versions returning
        # naive pandas timestamps; normalize at this source boundary only.
        if race.tzinfo is None:
            race = race.tz_localize("UTC")
        source["document"]["events"][key] = {
            "RoundNumber": int(number),
            "EventName": str(raw["EventName"]),
            "Location": str(raw["Location"]),
            "EventFormat": str(raw["EventFormat"]),
            "race_start": race.isoformat(),
        }
    raw = source["document"]["events"].get(key)
    if raw is None:
        raise DataError(f"Public history has no event {key}; refresh the dataset")
    date(raw["race_start"])
    return Event(raw)


def schedule(year):
    source = current()
    if source is None:
        return fastf1.get_event_schedule(year)
    if source["update"]:
        raw = fastf1.get_event_schedule(year)
        for number in raw["RoundNumber"]:
            if int(number) > 0:
                event(year, int(number))
    rows = [
        value
        for key, value in source["document"]["events"].items()
        if key.startswith(f"{year}/")
    ]
    if not rows:
        raise DataError(f"Public history has no {year} schedule")
    return pd.DataFrame(sorted(rows, key=lambda row: row["RoundNumber"]))


def scores(year, number, kind, load):
    source = current()
    if source is None:
        return load()
    key = f"{year}/{number}/{kind}"
    row = source["document"]["scores"].get(key)
    if row is None and source["update"]:
        # Whole-weekend completion is conservative for all session kinds.
        completed = date(event(year, number)["race_start"]) + pd.Timedelta(hours=6)
        if completed >= datetime.now(timezone.utc):
            raise DataError(f"Cannot archive unfinished session {key}")
        row = {"completed_at": completed.isoformat(), "values": load()}
        source["document"]["scores"][key] = row
    if row is None:
        raise DataError(f"Public history has no session {key}; refresh the dataset")
    if date(row["completed_at"]) >= datetime.now(timezone.utc):
        raise DataError(f"Future session in public history: {key}")
    return row["values"]


def fantasy_feed(path, load):
    source = current()
    if source is None:
        return load(path)
    day = path.removeprefix("drivers/").removesuffix("_en.json")
    completed = source["document"]["fantasy_events"].get(day)
    if completed is None or date(completed) >= datetime.now(timezone.utc):
        raise DataError(f"Cannot use unfinished Fantasy history {day}")
    rows = source["document"]["fantasy"].get(day)
    if source["update"]:
        fields = (
            "PlayerId",
            "PositionName",
            "IsActive",
            "QualifyingPoints",
            "RacePoints",
            "SprintPoints",
            "GamedayPoints",
            "SessionWisePoints",
            "Value",
        )
        rows = [
            {key: row[key] for key in fields if key in row}
            for row in load(path)["Value"]
        ]
        source["document"]["fantasy"][day] = rows
    if rows is None:
        raise DataError(f"Public history has no Fantasy scores for {day}")
    return {"Value": rows}


def racing_record(year, number, cutoff):
    source = current()
    if source is None:
        return None
    matches = [
        r
        for r in source["document"]["racing"]
        if r["season"] == year and r["round"] == number and date(r["end"]) < cutoff
    ]
    if len(matches) > 1:
        raise DataError("Duplicate racing history")
    return matches[0] if matches else None


def save_racing(row):
    source = current()
    if source and source["update"]:
        rows = source["document"]["racing"]
        rows[:] = [
            r
            for r in rows
            if (r["season"], r["round"]) != (row["season"], row["round"])
        ]
        rows.append(row)


def features(cutoff):
    source = current()
    if source is None or source["update"]:
        return None
    return [
        r
        for r in source["document"]["features"]
        if cutoff.year - 2 <= r["year"] <= cutoff.year
        and date(r["completed_at"]) < cutoff
    ]
