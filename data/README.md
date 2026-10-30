# Public historical inputs

`fantasy-evaluation.json` records chronological official-Fantasy validation and
per-session adoption decisions; see [the model documentation](../docs/fantasy-model.md).

`history.json` is a compact, versioned input dataset: completed session score
summaries, race classifications / championship points, calendar metadata,
official past-weekend Fantasy scores and recorded round prices, and date-stamped
telemetry features.
It contains no account credentials, cookies, private teams or raw telemetry.

Sources: public FastF1 completed-session data, official public Fantasy/Predict
feeds and explicitly stationary OpenF1 stop durations.
The source does not grant any additional redistribution rights to those feeds.

Regenerate from the repository root with:

```sh
python -m f1fantasy.refresh_history
```

Only the updater can download missing completed sessions. Website publication
reads this file strictly and fails closed when required historical inputs are
missing. Every historical observation must precede the forecast cutoff. Current
prices, active roster, schedule and Statistics are still fetched afresh.

Recorded prices supply the Garage's historical sparklines only. They are neither
future-price predictions nor a fallback for current prices. Missing history is
shown as unavailable rather than drawn as a synthetic trend.

The separate **Refresh public history** workflow updates this file after races;
the Pages workflow does not rebuild raw FastF1 history. Existing completed racing
records are reused, so the updater only loads newly completed racing sessions.
For upstream corrections, remove the affected racing record and rerun the updater.

The timing archive includes 66 GPs from 2024–2026, qualifying-phase gaps,
compound/lap-normalized pace, tyre/fastest-lap observations, weather/SC regimes
and cause-specific retirement labels. `stationary_stops` contains only verified
`stop_duration` observations; pit-lane transit is excluded. See
[racing model and evaluation](../docs/racing-model.md) for coverage, collection
commands, baseline losses and limitations. `racing-evaluation.json` is the offline
nested walk-forward report; no target outcomes fit their own forecasts.
