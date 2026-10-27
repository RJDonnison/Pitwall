"""Multi-weekend mixed-integer team and Boost optimization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .data import Asset, DataError, Weekend
from .projections import Estimate
from .chips import CHIPS, PREWEEK_CHIPS, ChipValues, components, valid_estimate


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
    chip: str | None = None
    x3: Asset | None = None
    session_points: Estimate | None = None


def optimize(
    assets: tuple[Asset, ...],
    weekends: list[Weekend],
    estimates: dict[tuple[int, str], Estimate],
    budget: int,
    previous: frozenset[str] | None = None,
    carry: int = 0,
    allow_penalties: bool = False,
    *,
    available_chips: frozenset[str] = frozenset(),
    chip_values: ChipValues | None = None,
    chip_reserve: dict[str, float] | None = None,
    eligible_chips: dict[int, frozenset[str]] | None = None,
    forced_chip: str | None = None,
    active_chip: str | None = None,
    limitless_restore: frozenset[str] | None = None,
) -> list[Lineup]:
    """Maximize total predicted points with net transfers and carry-over.

    Prices are held fixed for hypothetical later races; the next CLI run fetches
    real prices and re-optimizes. Budget is measured in $0.1m increments.
    """
    if not weekends or budget < 0 or carry not in (0, 1):
        raise ValueError("Invalid weekends, budget or carried transfer")
    ids = {a.id for a in assets}
    if active_chip is not None and active_chip not in PREWEEK_CHIPS:
        raise DataError("Active Final Fix requires remaining-session planning")
    if limitless_restore is not None and (
        len(limitless_restore) != 7
        or not limitless_restore <= ids
        or sum(a.id in limitless_restore and a.kind == "DRIVER" for a in assets) != 5
    ):
        raise DataError("Invalid verified Limitless restoration lineup")
    if active_chip == "limitless" and (
        (len(weekends) != 1 and limitless_restore is None) or previous is None
    ):
        raise DataError(
            "Active Limitless requires a previous team and verified restoration for a multi-week horizon; otherwise use a single-weekend plan"
        )
    if active_chip and forced_chip not in (None, active_chip):
        raise DataError("An active chip cannot be cancelled or replaced")
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
    if len(ids) != len(assets) or len(drivers) + len(constructors) != len(assets):
        raise DataError("Invalid or duplicate active assets")
    if previous is not None and sum(a.id in previous for a in drivers) != 5:
        raise DataError(
            "Previous lineup must contain five drivers and two constructors"
        )
    if any(w.season != weekends[0].season for w in weekends) or any(
        a.first_session >= b.first_session for a, b in zip(weekends, weekends[1:])
    ):
        raise DataError("Chip horizon must be chronological within one season")
    reserve = chip_reserve or {}
    if (
        not available_chips <= CHIPS
        or not reserve.keys() <= CHIPS
        or any(not np.isfinite(v) or v < 0 for v in reserve.values())
    ):
        raise DataError("Unknown chip or invalid chip reserve")
    if eligible_chips is not None and any(
        t not in range(len(weekends)) or not names <= CHIPS
        for t, names in eligible_chips.items()
    ):
        raise DataError("Invalid chip eligibility (use zero-based horizon indices)")
    allowed = [
        available_chips
        & PREWEEK_CHIPS
        & (eligible_chips.get(t, frozenset()) if eligible_chips is not None else CHIPS)
        for t, w in enumerate(weekends)
    ]
    for t, weekend in enumerate(weekends):
        if weekend.round == 1:
            allowed[t] = allowed[t] - {"wildcard", "limitless"}
    if previous is None:
        allowed[0] = allowed[0] - {"limitless"}
    if active_chip:
        allowed[0] = frozenset({active_chip})
        forced_chip = active_chip
    if forced_chip is not None and forced_chip not in allowed[0]:
        raise DataError(
            "Forced chip is unavailable or ineligible; Final Fix is future-only"
        )
    values = chip_values or ChipValues()
    for t, names in enumerate(allowed):
        if "no_negative" in names:
            for a in assets:
                delta = values.no_negative.get((t, a.id))
                if (
                    delta is None
                    or not valid_estimate(delta)
                    or min(components(delta)) < 0
                ):
                    raise DataError(f"Missing finite No Negative uplift for {a.name}")
        if "autopilot" in names:
            scenarios = values.autopilot.get(t, ())
            if not scenarios or any(
                a.id not in s or not valid_estimate(s[a.id])
                for s in scenarios
                for a in drivers
            ):
                raise DataError("Missing finite common Autopilot scenarios")
            for a in drivers:
                forecast = estimates.get((t, a.id))
                if (
                    forecast is None
                    or not valid_estimate(forecast)
                    or any(
                        not np.isclose(
                            sum(components(s[a.id])[k] for s in scenarios)
                            / len(scenarios),
                            components(forecast)[k],
                        )
                        for k in range(3)
                    )
                ):
                    raise DataError("Autopilot scenario means must equal forecasts")

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

    def both(left: int, right: int, value: float = 0) -> int:
        joint = var(value)
        row({joint: 1, left: -1}, high=0)
        row({joint: 1, right: -1}, high=0)
        row({joint: 1, left: -1, right: -1}, low=-1)
        return joint

    selected: list[dict[str, int]] = []
    boosted: list[dict[str, int]] = []
    incoming: list[dict[str, int]] = []
    extra: list[int | None] = []
    carried: list[int | None] = []
    durable: list[dict[str, int]] = []
    chips: list[dict[str, int]] = []
    tripled: list[dict[str, int]] = []
    for t, weekend in enumerate(weekends):
        h = {
            name: var(0 if t == 0 and name == active_chip else reserve.get(name, 0))
            for name in sorted(allowed[t])
        }
        chips.append(h)
        row({i: 1 for i in h.values()}, high=1)
        if t == 0 and forced_chip is not None:
            row({h[forced_chip]: 1}, low=1, high=1)
        x: dict[str, int] = {}
        b: dict[str, int] = {}
        z: dict[str, int] = {}
        persistent: dict[str, int] = {}
        triple: dict[str, int] = {}
        for asset in assets:
            score = estimates.get((t, asset.id))
            if score is None or not valid_estimate(score):
                raise DataError(f"Missing forecast for {asset.name} at {weekend.name}")
            x[asset.id] = var(-score.total)
            if asset.kind == "DRIVER":
                b[asset.id] = var(-score.total)
                row({b[asset.id]: 1, x[asset.id]: -1}, high=0)
                if "autopilot" in h:
                    # Cancel the ordinary extra Boost under Autopilot.
                    both(b[asset.id], h["autopilot"], score.total)
                if "x3" in h:
                    triple[asset.id] = var(-2 * score.total)
                    row({triple[asset.id]: 1, x[asset.id]: -1}, high=0)
                    row({triple[asset.id]: 1, b[asset.id]: 1}, high=1)
            if "no_negative" in h:
                uplift = values.no_negative[t, asset.id].total
                both(x[asset.id], h["no_negative"], -uplift)
                if asset.kind == "DRIVER":
                    both(b[asset.id], h["no_negative"], -uplift)
            persistent[asset.id] = var()
            ll = h.get("limitless")
            if ll is None:
                row({persistent[asset.id]: 1, x[asset.id]: -1}, low=0, high=0)
            else:
                # Scoring selection can differ only during Limitless.
                row({persistent[asset.id]: 1, x[asset.id]: -1, ll: -1}, high=0)
                row({persistent[asset.id]: -1, x[asset.id]: 1, ll: -1}, high=0)
                prior = (
                    durable[t - 1][asset.id]
                    if t
                    else int(
                        asset.id
                        in (
                            limitless_restore
                            if limitless_restore is not None
                            else previous
                        )
                    )
                )
                if t:
                    row({persistent[asset.id]: 1, prior: -1, ll: 1}, high=1)
                    row({persistent[asset.id]: -1, prior: 1, ll: 1}, high=1)
                else:
                    row({persistent[asset.id]: 1, ll: 1}, high=1 + prior)
                    row({persistent[asset.id]: -1, ll: 1}, high=1 - prior)
        row({x[a.id]: 1 for a in drivers}, low=5, high=5)
        row({x[a.id]: 1 for a in constructors}, low=2, high=2)
        prices = {x[a.id]: a.price for a in assets}
        if "limitless" in h:
            prices[h["limitless"]] = -max(0, sum(a.price for a in assets) - budget)
        row(prices, high=budget)
        row({i: 1 for i in b.values()}, low=1, high=1)
        if triple:
            row({**{i: 1 for i in triple.values()}, h["x3"]: -1}, low=0, high=0)
        if "autopilot" in h:
            for scenario in values.autopilot[t]:
                winners = []
                for a in drivers:
                    winner = var(-scenario[a.id].total / len(values.autopilot[t]))
                    winners.append(winner)
                    row({winner: 1, x[a.id]: -1}, high=0)
                # Maximizing the objective selects the best selected TOTAL weekend.
                row({**{i: 1 for i in winners}, h["autopilot"]: -1}, low=0, high=0)
        durable.append(persistent)
        tripled.append(triple)
        selected.append(x)
        boosted.append(b)
        if t == 0 and previous is None:
            incoming.append(z)
            extra.append(None)
            carried.append(None)
            continue
        for asset in assets:
            prior = durable[t - 1][asset.id] if t else int(asset.id in previous)
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
        penalty = var(10, ub=7 if allow_penalties else 0)
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
            if "limitless" in h:
                row({next_carry: 1, h["limitless"]: 1}, high=1)
            # Even a Wildcard cannot bank a transfer after using the allowance.
            carry_rule = {i: 1 for i in z.values()}
            carry_rule[next_carry] = 7
            if available is not None:
                carry_rule[available] = -1
            row(carry_rule, high=allowance + 6)
        for name in ("wildcard", "limitless"):
            if name in h:
                coefficients[h[name]] = -8
        row(coefficients, high=allowance)

    for name in PREWEEK_CHIPS:
        row({h[name]: 1 for h in chips if name in h}, high=1)

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
        options={"time_limit": 60, "mip_rel_gap": 0},
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
        chip = next((name for name, i in chips[t].items() if result.x[i] > 0.5), None)
        x3 = next(
            (a for a in d if a.id in tripled[t] and result.x[tripled[t][a.id]] > 0.5),
            None,
        )
        session = [
            sum(components(estimates[t, a.id])[k] for a in chosen) for k in range(3)
        ]
        if chip == "autopilot":
            scenarios = values.autopilot[t]
            for scenario in scenarios:
                winner = max(d, key=lambda a: scenario[a.id].total)
                for k in range(3):
                    session[k] += components(scenario[winner.id])[k] / len(scenarios)
        else:
            for k in range(3):
                session[k] += components(estimates[t, boost.id])[k]
        if x3 is not None:
            for k in range(3):
                session[k] += 2 * components(estimates[t, x3.id])[k]
        if chip == "no_negative":
            for k in range(3):
                session[k] += (
                    sum(components(values.no_negative[t, a.id])[k] for a in chosen)
                    + components(values.no_negative[t, boost.id])[k]
                )
        session_points = Estimate(*session)
        points = session_points.total - penalty
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
                chip,
                x3,
                session_points,
            )
        )
    return output
