# Roadmap

## Website — remaining-season planning (implemented)

- Static, responsive Pitwall interface with three locally saved manual teams, budgets, carried transfers and remaining/active chips.
- Browser HiGHS WebAssembly optimizes the remaining season jointly; show every selection's Q/S/R points, Boost, chips, changes, budget and penalties by round.
- GitHub Pages workflow publishes fresh public Python forecasts every two hours. Browser CORS restrictions require explicit labelled snapshot-preview consent when live verification fails; publications expire after six hours.
- Container deployment has been removed. The existing CLI tools remain available. Pages publication needs a GitHub remote/account and repository Pages configuration.

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
