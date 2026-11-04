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
python -m f1fantasy.prune_history
python -m f1fantasy.circuit_info
python -m f1fantasy.fantasy_model
python -m f1fantasy.racing_evaluation
python -m f1fantasy.model_compare
python -m f1fantasy.model_fit
```

`refresh_history` is the only publication path that downloads missing completed sessions. It writes `history.json` through a temporary file, so a failed refresh leaves the previous committed dataset intact. Website publication reads the committed history without downloading gaps and fails closed when required records are missing or malformed.

The **Refresh public history** workflow runs the updater, prunes unused history and first forecasts, and checks the publication path before committing the two archives. The Pages workflow reads that history, generates current Fantasy and Predict publications, and captures only the first eligible pre-weekend forecast for a round within the retention window. The **Fit model parameters** workflow runs after a successful history refresh. Each fitted family can move by at most one neighboring parameter step when the older folds, recent holdout and full paired sample pass the fit gates. When settings change, the workflow also refreshes `racing-evaluation.json`.

## Freshness and chronology

Every historical observation must precede the forecast cutoff. Completed-session records are reused instead of downloaded again. Recent racing records with missing timing are retried rather than archived immediately with permanent gaps, and practice pace is backfilled for at most three recent eligible races per refresh.

The retained model window is the selected season and the two preceding seasons. In 2027, pruning removes 2024 calendars, session scores, racing and telemetry summaries, stationary-stop observations, Predict race-control and pit-stop labels, and first-publication forecasts. Unreferenced historical Fantasy feeds are also removed. First publications inside the window remain immutable. The complete all-time GP winner facts are retained because questions about a new winner at a venue need that history; static evaluation reports and fitted settings are not rewritten by pruning.

`python -m f1fantasy.prune_history --season 2027` applies this retention policy without downloading anything. The history updater also prunes before enrichment, so old seasons cannot be rediscovered and downloaded through the retained records. It fetches schedules only for the three retained seasons, reuses completed session and stationary-stop records, and replaces a racing record only for the matching season and round. Older inputs remain in Git history if a historical evaluation needs them.

Calendar refresh replaces the selected year's round metadata and removes rounds no longer present in that source schedule, while retaining other years. New or reordered venues follow the official schedule rather than a fixed round list. Fantasy roster identities and team affiliations are read from the live feed; a new driver can use teammate and field priors before enough individual history exists. An unknown venue has no invented track history.

The updater discovers circuit pages from the official Formula 1 season calendar and refreshes their metadata daily. The `circuits` records in `history.json` contain lap length, scheduled laps, race distance, description, lap record, first Grand Prix, remote map and photograph URLs, source and check time. Pages must match the archived season, weekend dates and venue. The standalone `circuit_info` command refreshes this display metadata without downloading sessions or image files. A failed page refresh keeps the record's original provenance; a missing or mismatched venue is not filled with guessed information. Circuit metadata follows the same three-season retention window and is not a racing-model feature.

### Season rollover

Publication and history commands default to the current UTC year. Fantasy and Predict accept future seasons when their official feeds publish a matching calendar, active roster and the same validated game contracts. There is no 2026 cutoff. The existing scoring tables, chips and transfer costs are assumed unchanged; season, freshness, lock-state, option and payout validation still apply. Circuit pages and their map URLs are rediscovered each season, so new venues and published layout changes can update automatically. If current metadata is unavailable, existing guides retain their original source year. Weather still needs known circuit coordinates. A changed upstream game or page contract needs a code update.

Current Fantasy prices, active roster, schedule and Statistics are fetched afresh. Recorded round prices are used only for Garage sparklines. They are not future-price predictions or a fallback for current prices. Missing price history is shown as unavailable rather than synthesized.

For an upstream correction to an already archived race, remove the affected racing record and rerun the updater. Do not edit evaluation numbers or fitted settings by hand.

## Qualifying model selection

Race and qualifying adoption are checked separately. The timing model's lower combined error previously hid a worse pole forecast: pole Brier was 0.8634 against 0.8310 for the rank baseline, with log loss 2.1550 against 1.9441. Lower values are better. Qualifying now uses the rank baseline unless at least eight earlier scored folds support a timing model with better pole Brier and no worse pole log loss. Race and Sprint forecasts retain their existing selection.

The regenerated 51-event report includes a chronological `hybrid` replay. Its pole Brier is 0.8310 and pole log loss is 1.9441, while its race metrics are unchanged. This is development validation, not a claim of future accuracy. Each fold chooses its qualifying model before scoring that weekend.

## Coverage and provenance

The timing archive currently covers completed GPs from 2024 to 2026, with qualifying-phase gaps, compound and lap-normalized pace, tyre and fastest-lap observations, weather and safety-car regimes, and cause-specific retirement labels. `stationary_stops` contains only verified OpenF1 `stop_duration` observations; pit-lane transit is excluded. Evaluation files report development evidence, not a guarantee of future prediction accuracy.

Sources include public FastF1 completed-session data, official public Fantasy and Predict feeds, and explicitly stationary OpenF1 stop durations. Committing derived summaries does not grant additional redistribution rights to those sources. Large parsed FastF1 car and position telemetry is discarded from the ignored local cache after a verified compact summary is saved.
