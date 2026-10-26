# Roadmap

## V1 — Fantasy recommendations (implemented)

- CLI recommends five drivers, two constructors and a 2× Boost under the budget, with net transfers and one-week carry-over.
- Uses current-season Fantasy points and prices, FastF1 results, earlier visits to each circuit, and regular/Sprint weekend scoring.
- `preload --seasons 3` caches completed FastF1 sessions from the current and previous two seasons. Cached telemetry helps compare track characteristics and teammate-relative pace; missing data falls back to the results-based forecast.
- `backtest --compare-telemetry` compares historical prediction errors. Prices and eligible roster are fetched again for each recommendation. `--allow-old-prices` gives an explicitly provisional preview when the upcoming feed is unpublished.

## V2 — Fantasy account automation (planned)

- Model chip eligibility and scoring across regular and Sprint weekends, including Wildcard, Limitless, x3 Boost and Final Fix.
- Sync one F1 Fantasy team, then submit and verify selected transfers, Boost and chips against the live account.
- Schedule verified updates around actual Fantasy lock times on an always-on machine, with restart recovery and an audit log.

## V3 — official F1 Predict (planned)

- Fetch each round's real questions, answer choices, values and deadlines.
- Reuse the race forecast engine to choose valid answers with the highest expected Predict score and backtest by question type.
- Add authenticated submission and read-back verification after the recommendation workflow is proven.

The detailed working plan is in the local, Git-ignored `plan/current.md`.
