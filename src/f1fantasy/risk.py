"""Small-sample, regime-aware projections from completed Fantasy scores."""

from __future__ import annotations

from .data import Asset


def _recent(values: list[float]) -> float:
    weights = range(1, len(values) + 1)
    return sum(value * weight for value, weight in zip(values, weights)) / sum(weights)


def expected_session_points(
    driver: Asset,
    kind: str,
    history: dict[str, dict[str, list[float]]],
    drivers: list[Asset],
    fallback: float,
    *,
    race_finish_reference: float = 0,
) -> float:
    """Shrink severe-negative risk toward the teammate and current-season field.

    Scores at or below the published not-classified penalty are used as a
    *proxy* for that regime. Other negative scores remain finish outcomes.
    No target-weekend scores or future team data are used.
    """
    values = history.get(driver.id, {}).get(kind, [])
    if not values:
        return fallback
    penalty = -20 if kind == "R" else -10
    severe = lambda score: score <= penalty
    field = [
        score for asset in drivers for score in history.get(asset.id, {}).get(kind, [])
    ]
    team = [
        score
        for asset in drivers
        if asset.team_id == driver.team_id
        for score in history.get(asset.id, {}).get(kind, [])
    ]
    field_probability = sum(severe(score) for score in field) / len(field)
    team_probability = (
        sum(severe(score) for score in team) + 4 * field_probability
    ) / (len(team) + 4)
    prior_strength = 8 if kind == "R" else 10
    probability = (
        sum(severe(score) for score in values) + prior_strength * team_probability
    ) / (len(values) + prior_strength)
    # One exceptional overtake-heavy race must not dominate several weekends.
    finishes = (
        [min(score, 60) for score in values if not severe(score)]
        if kind == "R"
        else [score for score in values if not severe(score)]
    )
    teammate_finishes = [
        min(score, 60) if kind == "R" else score for score in team if not severe(score)
    ]
    if not finishes:
        finishes = teammate_finishes
    if not finishes:
        return fallback
    conditional = _recent(finishes)
    if kind == "S":
        # Sprint samples are sparse; borrow strength from full-race pace.
        reference = max(0, race_finish_reference) * 0.35
        conditional = (len(finishes) * conditional + 4 * reference) / (
            len(finishes) + 4
        )
    elif len(finishes) < 3 and teammate_finishes:
        conditional = (len(finishes) * conditional + 2 * _recent(teammate_finishes)) / (
            len(finishes) + 2
        )
    expectation = (1 - probability) * conditional + probability * penalty
    share = min(0.85, 0.5 + 0.1 * len(values))
    return share * expectation + (1 - share) * fallback
