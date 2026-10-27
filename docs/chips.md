# Chip optimization API

`optimize` retains its existing positional parameters and adds keyword-only:

```python
available_chips: frozenset[str] = frozenset()
chip_values: ChipValues | None = None
chip_reserve: dict[str, float] | None = None
eligible_chips: dict[int, frozenset[str]] | None = None
forced_chip: str | None = None
```

Inventory is explicitly **remaining** inventory. Names: `autopilot`, `x3`,
`no_negative`, `wildcard`, `limitless`, `final_fix`. Each can be spent once in
the single-season horizon, with at most one chip per weekend. `final_fix` is
excluded from pre-weekend decisions and cannot be forced there.

Eligibility keys are **zero-based horizon indices**, as in `estimates`. When
an eligibility mapping is supplied, omitted indices allow no chips. Otherwise
pre-weekend chips are allowed, except Wildcard/Limitless on championship round one. The caller must
verify account eligibility, including completion of the first weekend, and
pass the corresponding mapping. Autopilot, X3 and No Negative are immediately available. `forced_chip`
requires eligible remaining inventory and fixes the first horizon decision.
First-horizon Limitless requires `previous` to provide its restoration baseline.

Reserve values are finite, nonnegative expected points forgone by spending a
chip now rather than saving it beyond the horizon. The solver subtracts them
from its objective; reported `expected_points` do **not** subtract reserves.

## Empirical inputs

Import `ChipValues` and `load_chip_values` from `f1fantasy.chips`:

```python
values = load_chip_values(assets, weekends, estimates)
lineups = optimize(
    assets, weekends, estimates, budget, previous, carry,
    available_chips=remaining_inventory,
    eligible_chips=eligibility,
    chip_values=values,
    chip_reserve={"autopilot": 8.0},
)
```

`ChipValues.no_negative[(t, asset_id)]` is an `Estimate` of **uplifts** in
qualifying, sprint and race points, not a replacement forecast.
`ChipValues.autopilot[t]` is a tuple of equally likely scenarios, each mapping
every active driver ID to an `Estimate` of session outcomes. Each driver's
per-session sample means must equal the supplied forecast. Missing eligible
NN/AP inputs or nonfinite values fail closed. Inputs for ineligible chips are
not required. Custom callers can construct only the fields they need.

The loader fetches official `drivers/{gameday_id}_en.json` feeds through
`data._get_json`, using `data.season_weekends` to select current-season
weekends completed strictly before both the current time and
`weekends[0].first_session`. It uses at most
the last five weekends matching each predicted weekend's Sprint format. It
requires a common complete sample for all active assets and official session
totals consistent with `GamedayPoints`. It fails rather than imputing missing
history. No future-horizon actual results or cumulative season totals are used.

No Negative uplift is the mean official sessionwise
`nonegative_points - points`, including constructor-specific category adjustments.
A positive session can have a positive uplift: clamping net session scores is
incorrect. Sprint uplifts come only from Sprint weekends. The 2× driver's
uplift is counted twice.

Autopilot scenarios center historical driver session outcomes on forecast means,
retaining joint historical variation. Each scenario adds the maximum **total
weekend** score among the five selected drivers, replacing the ordinary fixed
Boost extra. It does not choose a separate winner per session. This is a small-
sample empirical approximation, not a calibrated joint predictive distribution;
one sample has no variation. NN uses empirical mean uplift rather than modeling
category-level outcomes conditional on the forecast. These approximations are
exactly optimized by the MILP; they are not claims of exact chip forecasts.

## Lineup output and transfers

New defaulted `Lineup` fields are `chip: str | None`, `x3: Asset | None` and
`session_points: Estimate | None`. Optimized outputs populate `session_points`
with chip-adjusted scoring before transfer penalties; `expected_points` is its
total minus `transfer_penalty`. The existing `boost` is always a selected driver.
Under Autopilot it remains the fallback fixed Boost; scoring uses scenario
winners. The X3 driver is selected, distinct from Boost, and gets two additional
copies of its score alongside the ordinary 2× driver.

Wildcard permits unlimited net transfers within budget with no penalty.
Limitless removes the scoring team's cap and transfer restriction, while
freezing a separate durable roster at its prior selection. The next round's
transfers compare against that restored roster. Limitless clears the next
carried transfer. Other rounds retain the ordinary unused-transfer bank (at
most one); Wildcard cannot bank a transfer after using its normal allowance.
`Lineup.transfers` reports net incoming **scoring** selections, including on
Limitless. Prices remain fixed across hypothetical later rounds as before.

## Final Fix

```python
decision = final_fix(
    original_lineup, active_assets, remaining_estimates, budget,
    available=True, eligible=True, accrued_points=already_scored_points,
)
```

`remaining_estimates: dict[str, Estimate]` must explicitly cover every active
asset and include **only still-unscored sessions**. `available` and `eligible`
are required booleans: the caller verifies inventory and the real session
window. This pure function does not infer a window, truncate elapsed forecasts,
fetch results, or activate a chip. `accrued_points` is the caller's already
multiplier-adjusted score and is retained verbatim.

The returned `FinalFix` retains `original`, `accrued_points`, `outgoing` and
`incoming` (both `None` when keeping the team), plus resulting `drivers`,
`constructors`, `boost`, `cost`, `remaining_points` and total `expected_points`.
It maximizes future points over zero or one budget-legal same-kind replacement;
replacing Boost transfers its multiplier to the incoming driver. It rejects
another active chip. Original team and accrued points are never rewritten.
Roster prices and remaining forecasts must be verified by the caller. There
is no scheduling, account mutation or CLI integration in this module.
