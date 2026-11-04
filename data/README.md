# Committed data artifacts

The files in this directory are public model inputs and reproducible development evidence. They contain no account credentials, cookies, private teams or raw telemetry.

## File roles

| File | Purpose |
| --- | --- |
| `history.json` | Compact, versioned history used by website publication and offline model work. It contains calendar metadata, completed session summaries, race classifications and championship points, official past-weekend Fantasy scores and prices, date-stamped telemetry features, Predict evidence and verified stationary pit-stop durations. |
| `forecast-archive.json` | The first eligible pre-weekend Fantasy publication captured for each season and round. Once a round is present, later publications do not replace it with hindsight. |
| `fantasy-evaluation.json` | Chronological official Fantasy validation, fitted feature choices and per-session adoption evidence. |
| `racing-evaluation.json` | Offline nested walk-forward report for the selected racing model. No target race fits its own forecast. |
| `model-comparison.json` | Paired walk-forward comparison of racing-model variants and baselines on the same folds and cutoffs. Pre-weekend and post-qualifying products remain separate. |
| `model-params.json` | Gated fitted settings loaded by the racing model. Missing, malformed or out-of-range settings are ignored in favor of code defaults. The file also keeps the 30 most recent fit log entries. |

## Regeneration

Run the relevant command from the repository root:

```sh
python -m f1fantasy.refresh_history
python -m f1fantasy.fantasy_model
python -m f1fantasy.racing_evaluation
python -m f1fantasy.model_compare
python -m f1fantasy.model_fit
```

`refresh_history` is the only publication path that downloads missing completed sessions. It writes `history.json` through a temporary file, so a failed refresh leaves the previous committed dataset intact. Website publication reads the committed history without downloading gaps and fails closed when required records are missing or malformed.

The **Refresh public history** workflow runs the updater and checks the publication path before committing `history.json`. The Pages workflow reads that history, generates current Fantasy and Predict publications, and commits a new `forecast-archive.json` entry only when the first eligible pre-weekend forecast for a round is available. The **Fit model parameters** workflow runs after a successful history refresh. Each fitted family can move by at most one neighboring parameter step when the older folds, recent holdout and full paired sample pass the fit gates. When settings change, the workflow also refreshes `racing-evaluation.json`.

## Freshness and chronology

Every historical observation must precede the forecast cutoff. Completed-session records are reused instead of downloaded again. Recent racing records with missing timing are retried rather than archived immediately with permanent gaps, and practice pace is backfilled for at most three recent eligible races per refresh.

The history updater requests the selected season and the two preceding seasons. Its compact telemetry feature list is limited to that three-year window. Existing completed racing and stationary-stop records are reused, while a newly saved racing record replaces only the matching season and round. Entering 2027 does **not** delete the archived 2024 racing records, schedules or first-publication evidence. Those records support historical evaluation even after the live forecast stops selecting them. The forecast archive has no automatic pruning path.

Calendar refresh replaces the selected year's round metadata and removes rounds no longer present in that source schedule, while retaining other years. New or reordered venues follow the official schedule rather than a fixed round list. Fantasy roster identities and team affiliations are read from the live feed; a new driver can use teammate and field priors before enough individual history exists. An unknown venue has no invented track history or circuit specifications.

### Season rollover

Publication and history commands default to the current UTC year, but an upstream calendar and active roster must be published before that year's site can generate fresh recommendations. The Fantasy scoring tables, chip rules and transfer costs remain implemented rules and need checking when the game changes. Predict explicitly accepts only its reviewed 2026 rules and rejects 2027 until those rules are reviewed. Circuit guides and specifications are also season-specific; they do not automatically become verified for a new season. Roster additions and reordered tracks are data changes, not evidence that every future F1 rule change is supported.

Current Fantasy prices, active roster, schedule and Statistics are fetched afresh. Recorded round prices are used only for Garage sparklines. They are not future-price predictions or a fallback for current prices. Missing price history is shown as unavailable rather than synthesized.

For an upstream correction to an already archived race, remove the affected racing record and rerun the updater. Do not edit evaluation numbers or fitted settings by hand.

## Qualifying model selection

Race and qualifying adoption are checked separately. The timing model's lower combined error previously hid a worse pole forecast: pole Brier was 0.8634 against 0.8310 for the rank baseline, with log loss 2.1550 against 1.9441. Lower values are better. Qualifying now uses the rank baseline unless at least eight earlier scored folds support a timing model with better pole Brier and no worse pole log loss. Race and Sprint forecasts retain their existing selection.

The regenerated 51-event report includes a chronological `hybrid` replay. Its pole Brier is 0.8310 and pole log loss is 1.9441, while its race metrics are unchanged. This is development validation, not a claim of future accuracy. Each fold chooses its qualifying model before scoring that weekend.

## Coverage and provenance

The timing archive currently covers completed GPs from 2024 to 2026, with qualifying-phase gaps, compound and lap-normalized pace, tyre and fastest-lap observations, weather and safety-car regimes, and cause-specific retirement labels. `stationary_stops` contains only verified OpenF1 `stop_duration` observations; pit-lane transit is excluded. Evaluation files report development evidence, not a guarantee of future prediction accuracy.

Sources include public FastF1 completed-session data, official public Fantasy and Predict feeds, and explicitly stationary OpenF1 stop durations. Committing derived summaries does not grant additional redistribution rights to those sources. Large parsed FastF1 car and position telemetry is discarded from the ignored local cache after a verified compact summary is saved.
