"""Recency and regulation-era weights shared by the race and Fantasy models.

Earlier versions weighted the last races linearly (1, 2, ... n) and gave a fixed
share to previous seasons. A walk-forward check on 2026 showed that early in a
new-regulation season, carrying the previous season at full weight clearly
worsened race-winner forecasts, while later in the season the window length
mattered little. These helpers replace both choices with:

* exponential recency decay, measured in races;
* a much smaller weight for results from an earlier technical-regulation era.

Everything here uses only dates/seasons already in the history, never the
target weekend's results.
"""

from __future__ import annotations

# First season of each technical-regulation era. Update when the rules change.
REGULATION_RESETS = frozenset({2014, 2022, 2026})

# Races for the weight of a result to halve. A fitted value is preferable once
# enough chronological walk-forward evaluation exists.
HALF_LIFE_RACES = 3.0

# Weight multiplier for a season from an earlier regulation era (car pace is
# largely not transferable), and per season back within the same era.
CROSS_ERA_WEIGHT = 0.1
SAME_ERA_DECAY = 0.5


def era(season: int) -> int:
    """Index of the regulation era containing ``season``."""
    return sum(reset <= season for reset in REGULATION_RESETS)


def season_weight(season: int, target_season: int) -> float:
    """Weight for a result from ``season`` when predicting ``target_season``."""
    if season >= target_season:
        return 1.0
    if era(season) < era(target_season):
        return CROSS_ERA_WEIGHT
    return SAME_ERA_DECAY ** (target_season - season)


def era_factor(seasons, target_season: int) -> float:
    """1.0 when any listed season shares the target's era, else the cross-era weight."""
    seasons = list(seasons)
    if any(era(s) == era(target_season) for s in seasons):
        return 1.0
    return CROSS_ERA_WEIGHT


def recency_weights(count: int, half_life: float | None = None) -> list[float]:
    """Oldest-to-newest weights; the newest result has weight 1."""
    half_life = HALF_LIFE_RACES if half_life is None else half_life
    return [0.5 ** ((count - 1 - i) / half_life) for i in range(count)]


def weights(seasons, target_season: int, half_life: float | None = None) -> list[float]:
    """Combined recency and era weights for chronologically ordered results.

    ``seasons`` holds each result's season, oldest first.
    """
    seasons = list(seasons)
    recency = recency_weights(len(seasons), half_life)
    return [r * season_weight(s, target_season) for r, s in zip(recency, seasons)]


def effective_sample_size(values) -> float:
    """Kish effective sample size of a set of weights."""
    values = [v for v in values if v > 0]
    if not values:
        return 0.0
    return sum(values) ** 2 / sum(v * v for v in values)
