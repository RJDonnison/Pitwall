# Fantasy points: joint features and official score validation

The Fantasy model is distinct from real-F1 probabilities and championship
points. `fantasy_model.py` learns **unboosted official Fantasy session totals**.
The optimizer subsequently applies Boost, chips, budget and net-transfer rules.
No Negative retains verified negative-category recovery with its target-session
downside floor; Autopilot uses joint scenarios centred on published forecasts.

## Inputs and cutoffs

The candidate uses 1,200 seeded joint racing draws per weekend, informed by
the enriched FastF1 archive described in [racing-model.md](racing-model.md).
Features include simulated positional points, grid-to-finish movement,
non-classification, fastest-lap probability, **joint** both-car/any-car Q3
probabilities, actual mechanical-status history and earlier official Fantasy
form. Constructor Q3 features count joint events instead of thresholding mean
driver scores. Historical teammate/car pace, classification causes,
tyre-informed fastest-lap opportunities and simulated grids feed those draws.

The feed does not expose enough category labels to claim separate overtaking,
Driver of the Day or pit-bonus predictions. The regression learns their
contribution to official session totals. Pit entry/exit transit times are not
stationary service times.

Historical targets have a conservative 72-hour pre-race embargo because the
compact calendar has no verified historical Fantasy editing deadline.
Racing-feature parameters are fitted on **preseason data**, not later results
in the evaluated Fantasy season. Regression coefficients and decay/penalty
choices use earlier scored weekends only. All participants in a weekend are
scored before any of that weekend's labels or validation errors enter training.

Qualifying and Sprint targets use official session scores. Race targets use
final `GamedayPoints - QualifyingPoints - SprintPoints`, matching the correction
for displayed subtotals. Missing/malformed targets are skipped; missing Sprint
points on a Sprint weekend are not silently zero. Evaluation is conditioned on
currently identified entrants, not a reconstruction of every historical entry
list. Official labels are archived finalized results, including recorded
corrections, rather than reconstructed first-publication versions.

Future rounds share one pre-weekend cutoff and fixed current roster/form.
Telemetry also precedes that cutoff. Actual target practice, qualifying grids,
future weather, target scores and target prices are excluded. Future prices
remain constant. There is no claim of category-level Fantasy uncertainty
intervals or a validated price-change model.

## Chronological evaluation and adoption

```sh
python -m f1fantasy.fantasy_model --output data/fantasy-evaluation.json
```

The command reads archived performance/score history and fetches current public
roster identities; historical Fantasy prices never enter features. The committed
report includes participant predictions/targets, cutoffs, earlier training rounds
and comparable baseline errors. It is development walk-forward evidence, not an
untouched holdout or calibrated accuracy claim.

Exponentially weighted ridge regression uses an unpenalized intercept and
weighted feature scaling. Candidate half-lives are 2/6/12 weekends and penalties
1/10/100. Each driver/constructor Q/S/R group chooses using earlier validation
errors. Adoption requires at least **five distinct scored weekends** and lower
MAE than both the existing estimator and preceding-three-score baseline.

Recorded 2026 evidence, as of 30 October:

| Group | Scored weekends | Candidate MAE | Existing MAE | Recent MAE | Used |
|---|---:|---:|---:|---:|---|
| Driver qualifying | 12 | 1.138 | 1.368 | 1.178 | Yes |
| Driver Sprint | 2 | 5.700 | 6.169 | 6.545 | No: sparse |
| Driver race | 12 | 10.520 | 11.256 | 11.644 | Yes |
| Constructor qualifying | 12 | 2.717 | 2.634 | 2.689 | No |
| Constructor Sprint | 2 | 9.753 | 9.739 | 9.909 | No |
| Constructor race | 12 | 15.998 | 16.560 | 16.874 | Yes |

Rejected/unsupported groups retain the existing official-score/venue/risk
estimator. Missing archive evidence also retains it. Non-default lookback or
disabled risk uses the existing model; `use_joint_model=False` supports baseline
evaluation. Static publication exposes group selection and metrics under
`model.fantasy` without copying all evaluation folds. Enriched racing summaries
can supply existing Fantasy score proxies without raw-session reloads; these
simplified position/grid/NC proxies remain distinct from official category scores.

## Wildcard comparisons

Wildcard makes transfers free **within the team's budget**. It does not equalize
budgets, restore other chips or remove future transfer constraints. The website
optimizes the remaining season, so carry and later chip opportunities can also
affect the current recommendation. Tied optima need not have a unique roster.

A regression verifies identical optimal roster/points for different starting
rosters with matching budget, active Wildcard and settings, while allowing
different net-transfer counts. Another verifies legitimate budget/inventory
differences. A live five-round comparison also matched with equal budget, carry
and inventory. No inconsistent Wildcard scoring was reproduced; optimizer rules
were not changed to force unequal profiles into the same plan.
