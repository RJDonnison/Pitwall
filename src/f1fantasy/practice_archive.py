"""Backfill archived practice pace so the practice weights can be fitted.

New races archive ``practice_pace`` as they are recorded; older races in
``history.json`` pre-date that. Each daily refresh backfills a few of the newest
ones (FastF1 practice laps are slow to load), so the fit gains evidence over time
without a one-off bulk download. A race with no practice timing is marked as
checked and retried only after ``RETRY`` so it is not downloaded every day.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import public_history, racing_data

RETRY = timedelta(days=30)
LIMIT = 3


def needs_practice(record: dict, now: datetime) -> bool:
    if record.get("practice_pace"):
        return False
    checked = record.get("practice_checked_at")
    return not checked or now - public_history.date(checked) >= RETRY


def backfill(document: dict, now: datetime, limit: int = LIMIT, loader=None) -> int:
    """Fill ``practice_pace`` on up to ``limit`` of the newest records lacking it."""
    loader = loader or racing_data._practice_pace
    done = 0
    for record in sorted(
        document.get("racing", []), key=lambda r: public_history.date(r["end"]), reverse=True
    ):
        if done >= limit:
            break
        if record["season"] < now.year - 2 or not needs_practice(record, now):
            continue
        sprint = "S" in record["sessions"]
        pace = loader(record["season"], record["round"], "sprint" if sprint else "conventional")
        record["practice_pace"] = pace
        record["practice_checked_at"] = now.isoformat()
        done += 1
        print(
            f"Practice pace {record['season']}/{record['round']}: "
            f"{', '.join(pace) or 'none available'}",
            flush=True,
        )
    return done
