# Racing-model evaluation and evidence

The racing model supplies **Race Insights and F1 Predict**, not Fantasy-category
points. Fantasy forecasting has a separate scoring and evaluation boundary.
All models remain uncalibrated. A larger dataset is not proof of accuracy.

## Historical inputs

The public archive contains 66 completed Grands Prix: all 24 rounds in 2024,
all 24 in 2025 and the first 18 in 2026, including qualifying, race, Sprint and
distinct Sprint-qualifying sessions. FastF1 supplies Q1/Q2/Q3 lap-percent gaps,
classifications, grids, real points, clean compound/lap-normalized pace, tyre age,
fastest-lap timing, lap number, stop counts, observed weather/SC/VSC/red-flag
regimes and mechanical/collision/driver-error/DSQ/DNS/unknown failure causes.
Pit, yellow/SC, inaccurate, deleted and opening laps are excluded from clean pace.
Classified late retirements retain their classification and failure cause as
separate targets. Retirement-lap proxies are completed laps plus one, not exact
incident timestamps.

OpenF1 adds **1,032 stationary stops from 37 races**. Only `stop_duration` is used;
`lane_duration`, deprecated `pit_duration` and FastF1 pit-entry/exit transit times
are never substituted. Coverage begins at the 2024 US GP and remains incomplete.
Missing durations are not inferred. The archive holds summaries, not raw telemetry
or account data. Current-weekend practice and actual grids remain excluded because
post-session editing authority has not been verified. Website weather forecasts
are display-only.

## Nested walk-forward comparison

```sh
python -m f1fantasy.racing_data --start-season 2024 --season 2026 --stationary-stops
python -m f1fantasy.racing_evaluation --output data/racing-evaluation.json
```

Evaluation is offline after collection. Each target uses only earlier completed
events. Compact calendars retain race start rather than a verified Fantasy lock;
evaluation adds a conservative 72-hour pre-race embargo. Parameters for a target
are selected using **earlier scored folds only**. Historical entry identities and
teams condition the evaluation; their results, timings and weather are not input
features. This is not a reconstructed historical account/roster/lock-time replay.

The committed report includes 50 scored events, fold cutoffs, training counts,
parameters, winner/pole multiclass Brier and log loss, podium/head-to-head Brier,
finish-distribution ranked probability score and winner reliability bins. Baselines
are the former rank bootstrap, uniform outcomes and a smoothed last-eight joint
ranking baseline. Lower losses are better.

| Metric | Timing candidate | Former rank model | Uniform | Last eight |
|---|---:|---:|---:|---:|
| Winner Brier | 0.8011 | 0.8538 | 0.9566 | 0.8939 |
| Pole Brier | 0.8718 | 0.8317 | 0.9543 | 0.8703 |
| Podium Brier | 0.0865 | 0.0905 | 0.1247 | 0.1056 |
| Head-to-head Brier | 0.1838 | 0.1860 | 0.2509 | 0.2175 |
| Position RPS | 0.1339 | 0.1355 | 0.1815 | 0.1579 |

**Pole predictions regress against the former model.** Adoption requires at least
eight validation events and improvement in winner Brier plus the sum of winner,
pole, podium and head-to-head Brier against every baseline. This aggregate gate
does not mean every market improved. Development walk-forward results are not an
untouched holdout or calibration certificate. Sparse/failing evaluations retain
the old model explicitly.

## Joint timing model

Half-life, temperature, team-shock share and simulated-grid weight are selected
chronologically. Current full-history selection: two-event half-life, temperature
0.8, team share 0.35, grid weight zero. A fixed four-observation prior is disclosed,
not described as fitted. Qualifying uses the best verified within-phase gap.

Current-car pace is pooled by team. Driver skill is relative to historical
teammates so car changes do not carry old-car absolute pace. Old-car evidence is
heavily reduced across the 2026 regulation boundary; older relative driver skill
has a separate weaker weight. Sparse Sprint/SQ forms borrow race/Q evidence.
Simulations share car/driver effects, bootstrap observed weekend weather and
incident regimes, condition races on simulated grids, pool mechanical
non-classification by team and draw other failures in shared event counts. DSQ/DNS
do not inflate mechanical risk. Power-unit-component hazards and exact incident
causality are not modeled. Race/Sprint fastest laps use separate timed histories
and observed fresh late-tyre opportunities instead of inverse-rank weights.

## Fastest stationary stop

The candidate shrinks robust crew log-time distributions toward the field, decays
old races and bootstraps shared race stop-opportunity counts. Each draw takes the
fastest service across each crew's opportunities. Rounded timing dead-heats are
excluded from unique-winner validation. It is used only after beating uniform and
smoothed winner-frequency Brier on at least eight earlier timing folds. Otherwise
an explicit time-decayed finalized official-winner prior is retained. Publication
cutoffs survive backfilled labels; unknown winner-team mappings fail closed.
Repair/red-flag services do not set the normal-service centre. This is not a
lap-by-lap strategy simulator; teams without timing history borrow the field prior.
