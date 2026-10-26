"""Multi-weekend mixed-integer team and Boost optimization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .data import Asset, DataError, Weekend
from .projections import Estimate


@dataclass(frozen=True)
class Lineup:
    weekend: Weekend
    drivers: tuple[Asset, ...]
    constructors: tuple[Asset, ...]
    boost: Asset
    cost: int
    expected_points: float
    transfers: int
    transfer_penalty: int


def optimize(
    assets: tuple[Asset, ...],
    weekends: list[Weekend],
    estimates: dict[tuple[int, str], Estimate],
    budget: int,
    previous: frozenset[str] | None = None,
    carry: int = 0,
    allow_penalties: bool = False,
) -> list[Lineup]:
    """Maximize discounted points with net incoming transfers and carry-over.

    Prices are held fixed for hypothetical later races; the next CLI run fetches
    real prices and re-optimizes. Budget is measured in $0.1m increments.
    """
    if not weekends or budget < 0 or carry not in (0, 1):
        raise ValueError("Invalid weekends, budget or carried transfer")
    ids = {a.id for a in assets}
    if previous is not None and (len(previous) != 7 or not previous <= ids):
        raise DataError(
            "Previous lineup must contain seven currently active Fantasy IDs"
        )
    if previous is None and carry:
        raise DataError("An initial team cannot have carried transfers")
    drivers = [a for a in assets if a.kind == "DRIVER"]
    constructors = [a for a in assets if a.kind == "CONSTRUCTOR"]
    if len(drivers) < 5 or len(constructors) < 2:
        raise DataError("Not enough active assets to form a team")

    objective: list[float] = []
    upper: list[float] = []
    integer: list[int] = []
    terms: list[dict[int, float]] = []
    lower_rows: list[float] = []
    upper_rows: list[float] = []

    def var(value: float = 0, ub: float = 1, integrality: int = 1) -> int:
        i = len(objective)
        objective.append(value)
        upper.append(ub)
        integer.append(integrality)
        return i

    def row(
        coefficients: dict[int, float], low: float = -np.inf, high: float = np.inf
    ) -> None:
        terms.append(coefficients)
        lower_rows.append(low)
        upper_rows.append(high)

    selected: list[dict[str, int]] = []
    boosted: list[dict[str, int]] = []
    incoming: list[dict[str, int]] = []
    extra: list[int | None] = []
    carried: list[int | None] = []
    for t, weekend in enumerate(weekends):
        x: dict[str, int] = {}
        b: dict[str, int] = {}
        z: dict[str, int] = {}
        weight = 0.85**t
        for asset in assets:
            score = estimates.get((t, asset.id))
            if score is None or not np.isfinite(score.total):
                raise DataError(f"Missing forecast for {asset.name} at {weekend.name}")
            x[asset.id] = var(-weight * score.total)
            if asset.kind == "DRIVER":
                b[asset.id] = var(-weight * score.total)
                row({b[asset.id]: 1, x[asset.id]: -1}, high=0)
        row({x[a.id]: 1 for a in drivers}, low=5, high=5)
        row({x[a.id]: 1 for a in constructors}, low=2, high=2)
        row({x[a.id]: a.price for a in assets}, high=budget)
        row({i: 1 for i in b.values()}, low=1, high=1)
        selected.append(x)
        boosted.append(b)
        if t == 0 and previous is None:
            incoming.append(z)
            extra.append(None)
            carried.append(None)
            continue
        for asset in assets:
            prior = selected[t - 1][asset.id] if t else int(asset.id in previous)
            z[asset.id] = var()
            incoming_constraint = {z[asset.id]: 1, x[asset.id]: -1}
            if t:
                incoming_constraint[prior] = 1
            row(incoming_constraint, low=0 if t else -prior)
            # New arrivals cannot count unless selected, and retained entries
            # cannot be counted as transfers.
            row({z[asset.id]: 1, x[asset.id]: -1}, high=0)
            if t:
                row({z[asset.id]: 1, prior: 1}, high=1)
            else:
                row({z[asset.id]: 1}, high=1 - prior)
        incoming.append(z)
        penalty = var(10 * weight, ub=7 if allow_penalties else 0)
        extra.append(penalty)
        available = carried[t - 1] if t else None
        next_carry = var() if t < len(weekends) - 1 else None
        carried.append(next_carry)
        allowance = 2 + (carry if t == 0 else 0)
        coefficients = {i: 1 for i in z.values()}
        coefficients[penalty] = -1
        if available is not None:
            coefficients[available] = -1
        if next_carry is not None:
            coefficients[next_carry] = 1
            row({next_carry: 7, penalty: 1}, high=7)
        row(coefficients, high=allowance)

    sparse_rows, sparse_columns, sparse_values = [], [], []
    for r, term in enumerate(terms):
        for c, value in term.items():
            sparse_rows.append(r)
            sparse_columns.append(c)
            sparse_values.append(value)
    matrix = coo_matrix(
        (sparse_values, (sparse_rows, sparse_columns)),
        shape=(len(terms), len(objective)),
    ).tocsr()
    result = milp(
        np.asarray(objective),
        integrality=np.asarray(integer),
        bounds=Bounds(np.zeros(len(objective)), np.asarray(upper)),
        constraints=LinearConstraint(matrix, lower_rows, upper_rows),
        options={"time_limit": 60, "mip_rel_gap": 0.005},
    )
    if result.x is None or result.status != 0:
        raise DataError(f"No verified optimal team (solver: {result.message})")
    output = []
    for t, weekend in enumerate(weekends):
        chosen = [a for a in assets if result.x[selected[t][a.id]] > 0.5]
        d = tuple(a for a in chosen if a.kind == "DRIVER")
        c = tuple(a for a in chosen if a.kind == "CONSTRUCTOR")
        boost = next(a for a in d if result.x[boosted[t][a.id]] > 0.5)
        transfers = sum(result.x[index] > 0.5 for index in incoming[t].values())
        penalty = 10 * round(result.x[extra[t]]) if extra[t] is not None else 0
        points = (
            sum(estimates[t, a.id].total for a in chosen)
            + estimates[t, boost.id].total
            - penalty
        )
        output.append(
            Lineup(
                weekend,
                d,
                c,
                boost,
                sum(a.price for a in chosen),
                points,
                transfers,
                penalty,
            )
        )
    return output
