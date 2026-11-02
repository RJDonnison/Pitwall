# Fitting the model weights automatically

`python -m f1fantasy.model_fit` tunes the racing model on the same walk-forward
backtest as `model_compare` (every race is predicted only from earlier races, with a
72-hour embargo) and writes `data/model-params.json`. `racing_model` loads that file;
a missing, malformed or out-of-range file is ignored and the hard-coded defaults apply.

## What is fitted

| Group | Parameters | Used for |
|---|---|---|
| `pre` | recency half-life, outcome spread, shared car effect, prior strength, retirement half-life and prior | every forecast before the weekend |
| `post_qualifying` | the same plus starting-grid weight | forecasts after qualifying when `starting_grid` is supplied |
| `practice` | qualifying and race practice weights | forecasts during practice; fitted only once 12 archived races carry `practice_pace` |

The objective is the sum of winner, pole, podium, head-to-head and not-classified Brier
scores (about 2.0).

## How a change is allowed

Each run evaluates the current settings and their one-rung neighbours. A change is
adopted only if all three hold:

1. the best neighbour, chosen on the older races only, gains at least 0.005 there;
2. it is not worse than the current settings on the latest 12 races, which were not used to choose it;
3. its full-sample gain is at least 0.005.

A run is skipped unless a new race has finished since the last fit, so settings move at
most one step per race and never refit on the same hold-out repeatedly.

## Result of the first fit (50 races, 2024 R9 to 2026 R18)

Only the pre-weekend group changed: the recency half-life went from 2.0 to **1.5 races**.

| | Defaults | Fitted |
|---|---|---|
| Objective | 2.0354 | 2.0124 |
| Winner Brier | 0.7964 | 0.7800 |
| Pole Brier | 0.8511 | 0.8450 |
| Podium Brier | 0.0882 | 0.0875 |
| Head-to-head Brier | 0.1857 | 0.1856 |
| Not-classified Brier | 0.1141 | 0.1143 |

* Gain over the defaults: **0.023 (about 1.1% of the objective)**, 90% paired interval
  [0.004, 0.043].
* Gain on the 12 latest races, which the choice did not use: 0.033, on a small sample.
* The overall comparison includes the races the step was chosen on, so it is optimistic;
  the hold-out figure is the clean one but is noisy.
* The post-qualifying settings did not change (no neighbour passed the gate). Practice
  weights are not fitted yet: 0 of 12 races carry practice pace.

**The improvement is small.** Recent form matters slightly more than the original
settings assumed, and nothing else moved. The value of the job is that settings now follow
the data as it grows instead of staying at hand-picked values, without risking a
step that only fits noise.

## CI/CD

* `.github/workflows/model-fit.yml` runs after every successful `Refresh public history`
  (or manually, with an optional force). It fits, runs the model and web-data tests
  against the fitted file, regenerates `data/racing-evaluation.json` if the file changed,
  and commits to `main`. The Pages workflow then publishes it.
* The daily history refresh also backfills practice pace for up to three of the newest
  races lacking it (`practice_archive`), so the practice weights become fittable in a few
  weeks without a bulk download.
* The site shows the latest fit in Race Insights ("How the model tunes itself"): the
  settings, backtest score against the defaults with its interval, the last decision and
  the practice status. It comes from `model.fit` in `forecast.json`.

## Limits

Brier differences of this size on 50 races are close to Monte Carlo and sampling noise
(a 300-simulation run chose a different first step than a 600-simulation run, so CI uses
1000). The gate exists to keep noise from moving the model; it does not make a 1% gain
certain.
