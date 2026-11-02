"""Lap data of a FastF1 session, or ``None`` when timing was not available.

``Session.load(laps=True)`` can finish without lap timing (the upstream feed is
late or missing for that session). Reading ``session.laps`` then raises
``DataNotLoadedError``, which is not an ``AttributeError``, so ``getattr(...,
None)`` does not protect callers. A session without lap timing still has results,
so callers treat the laps as absent instead of failing the whole refresh.
"""

from __future__ import annotations


def loaded_laps(session):
    try:
        laps = session.laps
    except Exception as exc:  # DataNotLoadedError, or a partially loaded session
        if type(exc).__name__ != "DataNotLoadedError":
            raise
        return None
    return laps
