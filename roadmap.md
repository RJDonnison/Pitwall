# Roadmap

## Website — remaining-season planning (implemented)

- Static, responsive Pitwall interface with three locally saved manual teams, budgets, carried transfers and remaining/active chips.
- Browser HiGHS WebAssembly optimizes the remaining season jointly; show every selection's Q/S/R points, Boost, chips, changes, budget and penalties by round.
- GitHub Pages workflow publishes fresh public Python forecasts every two hours. Browser CORS restrictions use a labelled snapshot preview automatically when live verification is unavailable; publications still expire after six hours.
- Container deployment has been removed. The existing CLI tools remain available; publication uses the repository's GitHub Pages workflow.
- Publication refreshes market inputs and forecasts every two hours; a separate daily/manual job updates the committed public historical dataset. These are scheduled snapshots, not live race streaming.

## Website versions — implementation order

### V5 — UI remake (implemented)

- Follow the supplied `DESIGN.md` Grand Prix Broadsheet system and the Visual Strategy/Garage and dedicated mobile Stitch references, with compact roster rows, horizontal team tabs and fixed mobile navigation.
- Race-specific circuit Strategy with transfer/Boost/chip directives, net score comparisons, cumulative remaining-season points, selectable round cards and exact seven-selection breakdowns.
- Full-width Team Garage with three existing local profiles, licensed driver/car photographs, actual recorded round-price sparklines, capital allocation, price-focused asset registry, coloured/grey chip controls, budget/free-transfer settings and JSON import/export.
- The requested TracingInsights 2026 driver/car set is matched by current team and driver; exact source/licence records and separately licensed archival venue photos are in the credits.
- Calculate automatically after complete-team changes and foreground publication updates, without changing page, focus or chip-toggle scroll position. Preserve the optimizer, local-storage format, labelled snapshot state, expiry/conflict checks, keyboard focus and reduced-motion support. Mockup-only lock timers, weather and confidence statistics are not presented as live data.

### V6 — Race Insights page (implemented)

- Stitch-derived responsive page with per-round driver/team probabilities, regular/Sprint outcome selection, searchable historical seasons and a separate Fantasy breakdown.
- Official finalized stationary-stop winner history supplies prior-smoothed fastest-stop probabilities with dated evidence.
- Real F1 championship projections retain historical participants and original team attribution. Central 80% ranges use joint season samples; missing current-season coverage disables totals and partial seasons are labelled.
- Visible sample sizes, cutoff, model/seed, sources and uncalibrated status. See [methodology](docs/website.md#v6-race-insights).

### V7 — Weather-aware race model (implemented; forward evaluation collecting)

- The V5 Strategy page already displays sourced track specifications and optional public weather context. This version adds weather to the predictive model, rather than treating that display as a model improvement.
- Add sourced, timestamped weather forecasts and condition classification, such as dry, wet and changeable, to the race model.
- Evaluate effects on pace, reliability and qualifying/Sprint/race outcomes using only weather information available at prediction time.
- Compare chronologically against the existing model before claiming improved predictions; expose uncertain or missing weather inputs.
- Daily weather classifications drive a shrunk official-score analogue candidate for Q/S/R. Candidate predictions stay separate from the selected optimizer until forward evidence supports a change. First pre-weekend publications are preserved in `data/forecast-archive.json` by Pages.

### V8 — Forecast confidence and accuracy scores

- Show MAE (mean absolute error) in Fantasy points, with predicted-versus-actual history for drivers, constructors and qualifying/Sprint/race forecasts. Include sample counts, evaluation dates and model version.
- Evaluate archived pre-weekend predictions chronologically against finalized results; exclude current-weekend outcomes from training, calibration and the original prediction. Compare against a clearly identified baseline.
- Add empirically calibrated prediction ranges and show their measured coverage. Keep historical accuracy separate from confidence in an individual forecast; MAE is not a confidence percentage.
- Distinguish regular and Sprint weekends and disclose sparse or missing evidence. Show unavailable or insufficient-history states instead of invented confidence scores.
- Where supported by joint outcome evidence, expose uncertainty in recommended changes and team totals, accounting for correlated driver/constructor and chip effects rather than simply adding individual errors.
- Use defined text confidence labels; keep numeric confidence scores rare. Prioritize error bars and visual error comparisons.

### V9 — Website prediction system

- Fetch the latest official F1 Predict questions, legal answer choices, variable payouts and lock state.
- Bring the existing CLI expected-points model to the website: calculate the highest expected-scoring valid answers, ordered podium and question Boost, with probability and points breakdowns.
- Keep Predict scoring distinct from Fantasy and fail clearly on unsupported questions or unverifiable data.

## V1 — Fantasy recommendations (implemented)

- CLI recommends five drivers, two constructors and a 2× Boost under the budget, with net transfers and one-week carry-over.
- Uses current-season Fantasy points and prices, FastF1 results, earlier visits to each circuit, and regular/Sprint weekend scoring.
- `preload --seasons 3` summarizes completed FastF1 sessions from the current and previous two seasons, retaining compact telemetry features and small results caches. Cached telemetry helps compare track characteristics and teammate-relative pace; missing data falls back to the results-based forecast.
- `backtest --compare-telemetry` compares historical prediction errors. Prices and eligible roster are fetched again for each recommendation. `--allow-old-prices` gives an explicitly provisional preview when the upcoming feed is unpublished.
- V1 gives current-season form the strongest historical weight; the official Fantasy Statistics feed cross-checks current prices and season points. `backtest --show-points` exposes full predicted-versus-actual scores.
- Every CLI command supports versioned `--format json` output for `jq` and automation, while retaining text by default. `clear-team` removes only the locally imported team.

## V2 — model learning and evaluation (planned)

- Build point-in-time driver and constructor training examples using only data available before each weekend, with separate qualifying, Sprint and race targets.
- Split completed weekends **chronologically**: fit weights on earlier races, choose among candidates on later validation races, and measure improvement once on a final untouched test block. Use walk-forward validation as more races become available.
- Add `f1fantasy train` to produce a versioned model for recent form, same-circuit history and telemetry. Compare it with the current fixed-weight and results-only forecasts, reporting regular and Sprint errors and sample counts separately.
- Promote a candidate only if it improves the held-out evaluation; keep the previous model available for rollback. After evaluation, refit the approved approach on all completed races for future recommendations without rewriting its historical test result.
- Consider an **opt-in** cache-compaction command that retains verified prediction features and the results data needed by the CLI while reclaiming bulky raw telemetry after preloading is complete.

## V3 — Fantasy account automation (implemented, optional CLI)

- Model chip eligibility and scoring across regular and Sprint weekends, including Wildcard, Limitless, x3 Boost and Final Fix.
- Sync one F1 Fantasy team, then submit and verify selected transfers, Boost and chips against the live account.
- Optional CLI scheduling on an always-on machine requires verified actual Fantasy lock times, restart recovery and an audit log. The static website does not submit account changes.

## V4 — official F1 Predict (implemented, CLI)

- Fetch each round's real questions, answer choices, values and deadlines.
- Reuse the race forecast engine to choose valid answers with the highest expected Predict score and backtest by question type.
- Add authenticated submission and read-back verification after the recommendation workflow is proven.

The detailed working plan is in the local, Git-ignored `plan/current.md`.
