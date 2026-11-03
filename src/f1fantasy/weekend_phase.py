"""Where a race weekend is, and what the published forecasts may do about it.

Forecasts keep refreshing through practice, because practice pace is real
pre-qualifying evidence. They pause when Grand Prix qualifying starts (the grid
and the Fantasy lock make later changes a different product) and resume once
the race has finished. While paused, or whenever a refresh fails, the last
published forecast stays on the site.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .data import Weekend

OPEN, PRACTICE, PAUSED = "open", "practice", "paused"


@dataclass(frozen=True)
class Phase:
    state: str  # open | practice | paused
    weekend: Weekend | None  # the weekend in progress (practice/paused), else None
    pause_at: datetime | None = None
    resume_after: datetime | None = None
    practice: tuple[str, ...] = ()  # official names of finished practice sessions

    def describe(self) -> dict:
        label = {
            OPEN: "Forecasts refresh normally before the weekend.",
            PRACTICE: "Practice is under way. Forecasts update with each completed session until qualifying.",
            PAUSED: "Predictions are paused from qualifying until the race finishes, then resume for the next round.",
        }[self.state]
        return {
            "state": self.state,
            "label": label,
            "round": self.weekend.round if self.weekend else None,
            "weekend": self.weekend.name if self.weekend else None,
            "paused_at": self.pause_at.isoformat() if self.pause_at else None,
            "resumes_after": self.resume_after.isoformat() if self.resume_after else None,
            "practice_sessions": list(self.practice),
        }


def pause_start(weekend: Weekend) -> datetime:
    """Start of Grand Prix qualifying; the second-to-last session if unnamed."""
    named = [start for name, start, _ in weekend.sessions if name.strip().casefold() == "qualifying"]
    if named:
        return min(named)
    if len(weekend.sessions) >= 2:
        return weekend.sessions[-2][1]
    return weekend.first_session


def practice_sessions(weekend: Weekend, now: datetime) -> tuple[str, ...]:
    """Practice sessions that have finished and precede the pause."""
    pause = pause_start(weekend)
    return tuple(
        name
        for name, _, end in weekend.sessions
        if name.strip().casefold().startswith("practice") and end <= now and end <= pause
    )


def phase(weekends: list[Weekend], now: datetime) -> Phase:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    for weekend in sorted(weekends, key=lambda w: w.first_session):
        if weekend.last_session is None or not weekend.first_session <= now <= weekend.last_session:
            continue
        pause = pause_start(weekend)
        if now >= pause:
            return Phase(PAUSED, weekend, pause, weekend.last_session)
        return Phase(PRACTICE, weekend, pause, weekend.last_session, practice_sessions(weekend, now))
    return Phase(OPEN, None)
