"""Lap data of a FastF1 session, or ``None`` when timing was not available.

``Session.load(laps=True)`` can finish without lap timing (the upstream feed is
late or missing for that session). Reading ``session.laps`` then raises
``DataNotLoadedError``, which is not an ``AttributeError``, so ``getattr(...,
None)`` does not protect callers. A session without lap timing still has results,
so callers treat the laps as absent instead of failing the whole refresh.
"""

from __future__ import annotations


def loaded_laps(session):
    return loaded(session, "laps")


def loaded(session, name):
    """Any lazily loaded FastF1 session property (``laps``, ``weather_data``,
    ``results``, ...), or ``None`` when that part of the session was not loaded.

    FastF1 raises ``DataNotLoadedError`` (not an ``AttributeError``) for a part
    that ``Session.load`` skipped or could not fetch, so ``getattr(session, name,
    None)`` does not protect callers. Other errors still propagate.
    """
    try:
        return getattr(session, name)
    except Exception as exc:
        if type(exc).__name__ != "DataNotLoadedError":
            raise
        return None
