"""Immutable first pre-weekend publications and finalized official settlements."""

import json
import math
from pathlib import Path

from . import public_history
from .data import DataError

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "forecast-archive.json"


def load(path=DEFAULT):
    if not Path(path).exists():
        return {"schema": 1, "forecasts": []}
    result = json.loads(Path(path).read_text())
    if result.get("schema") != 1 or not isinstance(result.get("forecasts"), list):
        raise DataError("Unsupported forecast archive")
    return result


def capture(archive, publication):
    """Freeze the first eligible snapshot per round; never replace with hindsight."""
    known = {(r["season"], r["round"]) for r in archive["forecasts"]}
    for row in publication["rounds"][:1]:
        key = publication["season"], row["round"]
        if key in known or public_history.date(
            publication["generated_at"]
        ) >= public_history.date(row["first_session_utc"]):
            continue
        archive["forecasts"].append(
            {
                "season": key[0],
                "round": key[1],
                "gameday_id": row["gameday_id"],
                "sprint": row["sprint"],
                "first_session_utc": row["first_session_utc"],
                "generated_at": publication["generated_at"],
                "cutoff": publication["forecast_cutoff"],
                "model": publication["model"],
                "assets": publication["assets"],
                "forecasts": row["forecasts"],
                "weather_model": row.get("weather_model"),
                "baseline": row.get("baseline", {}),
                "weather": row.get("weather"),
                "intervals": row.get("intervals", {}),
            }
        )
        known.add(key)


def settled(archive, document, cutoff):
    """Return only complete official labels whose finalization precedes evaluation."""
    result = []
    for entry in archive["forecasts"]:
        day = str(entry["gameday_id"])
        end = document.get("fantasy_events", {}).get(day)
        if not end or public_history.date(end) >= cutoff:
            continue
        if not (
            public_history.date(entry["generated_at"])
            < public_history.date(entry["first_session_utc"])
            and public_history.date(entry["cutoff"])
            <= public_history.date(entry["generated_at"])
        ):
            continue
        # A season and round match prevents reused gameday identifiers settling
        # an archive against a different year's outcome.
        matches = [
            r
            for r in document.get("racing", [])
            if r["season"] == entry["season"]
            and r["round"] == entry["round"]
            and abs(
                (
                    public_history.date(r["end"]) - public_history.date(end)
                ).total_seconds()
            )
            < 43200
        ]
        if len(matches) != 1:
            continue
        labels = {}
        for row in document.get("fantasy", {}).get(day, []):
            try:
                q = float(row["QualifyingPoints"])
                s = float(row["SprintPoints"]) if entry["sprint"] else 0.0
                race = float(row["GamedayPoints"]) - q - s
                if all(math.isfinite(v) for v in (q, s, race)):
                    labels[str(row["PlayerId"])] = [q, s, race]
            except (KeyError, TypeError, ValueError):
                continue
        result.append(
            {
                **entry,
                "actual": labels,
                "evaluated_at": cutoff.isoformat(),
                "completed_at": end,
            }
        )
    return sorted(result, key=lambda r: (r["season"], r["round"]))


def save(archive, path=DEFAULT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(archive, sort_keys=True, allow_nan=False, separators=(",", ":"))
        + "\n"
    )
    temporary.replace(path)
