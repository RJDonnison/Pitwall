# Racing-model evaluation: every variant, one backtest

Reproduce: `python -m f1fantasy.model_compare` (about 15 minutes at 1000
simulations; writes `data/model-comparison.json`).

All variants are scored on the same 50 races (2024 round 9 to 2026 round 18),
the same 72-hour pre-race embargo and the same metrics. Hyper-parameters of each
tuned family are chosen *nested*: before scoring race k, the configuration with
the best mean objective over races earlier than k is used. Lower is better.
Objective = winner + pole + podium + head-to-head + not-classified Brier.

`pre` variants use only information available before the weekend. `post-quali`
variants also use the known starting grid and are a different product (a forecast
refreshed after qualifying); never compare them to `pre` as like for like.

| Variant | Info | Winner Brier | Pole Brier | Podium Brier | Head-to-head | Position RPS | NC Brier | Either-car NC |
|---|---|---|---|---|---|---|---|---|
| Uniform | pre | 0.953 | 0.956 | 0.124 | 0.250 | 0.181 | 0.135 | 0.238 |
| Last 8 races | pre | 0.893 | 0.879 | 0.106 | 0.217 | 0.158 | 0.126 | 0.208 |
| Rank model v1 | pre | 0.848 | **0.833** | 0.090 | 0.186 | 0.136 | 0.116 | 0.175 |
| v2 (before NC change) | pre | **0.780** | 0.868 | **0.087** | 0.184 | 0.134 | 0.117 | 0.181 |
| v2 + team-weighted NC (shipped) | pre | 0.783 | 0.867 | 0.088 | 0.184 | 0.134 | **0.114** | **0.174** |
| Plackett-Luce | pre | 0.858 | 0.840 | 0.092 | 0.182 | 0.133 | 0.115 | 0.175 |
| v2 + actual grid | post-quali | 0.589 | 0.863 | 0.068 | 0.168 | 0.124 | 0.114 | 0.175 |
| Plackett-Luce + actual grid | post-quali | 0.636 | 0.895 | 0.074 | 0.171 | 0.125 | 0.115 | 0.175 |

Paired differences against v2 before the NC change (negative is better, 90%
bootstrap interval) are in `data/model-comparison.json`.

## What the backtest says

* **Team-weighted NC** (shipped): NC Brier -0.0024 [-0.0041, -0.0008] and
  either-car NC -0.0067 [-0.0108, -0.0028]; winner, pole, podium, head-to-head and
  position scores are within noise (winner +0.003 [-0.001, +0.008]).
* **Plackett-Luce does not beat v2 before the weekend.** Its winner Brier is worse
  (+0.078 [+0.028, +0.131]); it is better only on pole, where the interval touches
  zero. It stays in the harness as a competitor, not as the model.
* **The known starting grid is the largest gain available**: winner Brier
  -0.191 [-0.285, -0.093], podium -0.019, head-to-head -0.016, position RPS -0.010.
  The tuned post-qualifying settings (`racing_model.POST_QUALIFYING_PARAMETERS`) sit on
  a plateau: grid_weight 2 to 3.5 scored within 0.01 of each other, and the nested
  score (1.796) is close to the in-sample best (1.779), so the gain is not selection
  noise. This is exposed as `draw(..., grid=...)` and `predict_model._draw(...,
  grid=...)`. It is opt-in, and no pre-weekend forecast uses it.
* **Re-tuning the pre-weekend parameters did not help.** A 300-configuration search
  gave in-sample 2.002 against 2.034 for the shipped defaults, but the nested score
  was 2.042: worse than the defaults. The shipped parameters stay.
* **Open weakness:** v2 is worse than rank model v1 on pole (0.868 against 0.833,
  interval [-0.069, -0.003] for v1 being better). Qualifying prediction is the
  obvious next thing to improve.

## Not covered

The Fantasy points model and the history-weights commit are not part of this
harness. They need official Fantasy scores and prices, which this offline dataset
does not hold; they still need their own backtest.
