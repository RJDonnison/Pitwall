"""Current-weekend practice pace, available before qualifying.

Each completed practice session contributes every driver's representative fast
pace: the mean of their best three clean laps, each expressed as a percentage
off the field's median on the same lap number and tyre compound (which removes
fuel load, track evolution and compound effects, as for historical sessions).
Later sessions weigh more because the track and set-ups converge. The result is
a field-relative evidence signal for the models, never a lap-time prediction.
"""

from __future__ import annotations

import numpy as np

from . import data
from .session_laps import loaded_laps

BEST_LAPS = 3
MIN_LAPS = 2
SESSION_WEIGHT = {"FP1": 1.0, "FP2": 2.0, "FP3": 3.0}


def identifier(name: str) -> str | None:
    """'Practice 2' -> 'FP2'; anything else is not practice."""
    text = name.strip().casefold()
    if text.startswith("practice") and text.split()[-1].isdigit():
        return f"FP{int(text.split()[-1])}"
    return None


def session_pace(session) -> dict[str, float]:
    """Driver code -> pace gap (percent, lower is faster) from one session's laps."""
    laps = loaded_laps(session)
    if laps is None or laps.empty or "LapTime" not in laps:
        return {}
    mask = laps["LapTime"].notna()
    if "IsAccurate" in laps:
        mask &= laps["IsAccurate"].fillna(False).astype(bool)
    for field in ("PitInTime", "PitOutTime"):
        if field in laps:
            mask &= laps[field].isna()
    if "Deleted" in laps:
        mask &= ~laps["Deleted"].fillna(False).astype(bool)
    clean = laps.loc[mask].copy()
    if clean.empty:
        return {}
    clean["seconds"] = clean["LapTime"].dt.total_seconds()
    groups = clean.groupby(["LapNumber", "Compound"])["seconds"]
    count = groups.transform("count")
    clean["gap"] = np.where(count >= 3, 100 * (clean["seconds"] / groups.transform("median") - 1), np.nan)
    clean = clean.dropna(subset=["gap"])
    pace = {}
    for driver, rows in clean.groupby("Driver"):
        best = np.sort(rows["gap"].to_numpy())[:BEST_LAPS]
        if len(best) >= MIN_LAPS and np.all(np.isfinite(best)):
            pace[str(driver)] = float(best.mean())
    return pace


def combine(sessions: dict[str, dict[str, float]]) -> dict[str, float]:
    """Weighted mean over sessions, then centred on the field (mean zero)."""
    totals: dict[str, list[float]] = {}
    for key, pace in sessions.items():
        weight = SESSION_WEIGHT.get(key, 1.0)
        for driver, value in pace.items():
            entry = totals.setdefault(driver, [0.0, 0.0])
            entry[0] += weight * value
            entry[1] += weight
    means = {driver: total / weight for driver, (total, weight) in totals.items()}
    if not means:
        return {}
    centre = float(np.mean(list(means.values())))
    return {driver: value - centre for driver, value in means.items()}


def load(season: int, round_number: int, names, *, loader=None) -> dict[str, float]:
    """Pace for the finished practice sessions ``names`` (official session names).

    ``loader(season, round, identifier)`` returns a loaded session; the default
    uses FastF1 with laps only. Failure to load a session is a data error: the
    caller falls back to forecasts without practice rather than guessing.
    """
    from .history import configure_cache

    sessions: dict[str, dict[str, float]] = {}
    for name in names:
        key = identifier(name)
        if key is None:
            continue
        try:
            if loader is None:
                import fastf1

                configure_cache()
                session = fastf1.get_session(season, round_number, key)
                session.load(laps=True, telemetry=False, weather=False, messages=False)
            else:
                session = loader(season, round_number, key)
            pace = session_pace(session)
        except Exception as exc:  # FastF1 raises many exception types
            raise data.DataError(f"Cannot load {key} laps for round {round_number}: {exc}") from exc
        if pace:
            sessions[key] = pace
    return combine(sessions)


# Share of the standardised points spread taken from practice pace (see
# racing_model.PRACTICE_WEIGHT for why these are priors, not fitted values).
POINTS_WEIGHT = {"qualifying": 0.25, "race": 0.15}
MIN_DRIVERS = 5


def shrink_scores(scores: dict[str, float], pace: dict[str, float], weight: float) -> dict[str, float]:
    """Move driver point estimates toward their practice order, keeping the spread.

    ``scores`` maps driver code to expected points (higher is better); ``pace``
    maps driver code to a field-centred gap (lower is faster). Both are z-scored
    over the drivers present in both; others are returned unchanged.
    """
    common = [t for t in scores if t in pace]
    if weight <= 0 or len(common) < MIN_DRIVERS:
        return dict(scores)
    values = np.array([scores[t] for t in common], dtype=float)
    observed = -np.array([pace[t] for t in common], dtype=float)
    spread, scale = float(values.std()), float(observed.std())
    if spread <= 0 or scale <= 0:
        return dict(scores)
    z_score = (values - values.mean()) / spread
    z_pace = (observed - observed.mean()) / scale
    adjusted = values.mean() + spread * ((1 - weight) * z_score + weight * z_pace)
    result = dict(scores)
    result.update({t: float(v) for t, v in zip(common, adjusted)})
    return result
