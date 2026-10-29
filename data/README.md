# Public historical inputs

`history.json` is a compact, versioned input dataset: completed session score
summaries, race classifications / championship points, calendar metadata,
official past-weekend Fantasy scores and date-stamped telemetry features.
It contains no account credentials, cookies, private teams or raw telemetry.

Sources: public FastF1 completed-session data and official public Fantasy feeds.
The source does not grant any additional redistribution rights to those feeds.

Regenerate from the repository root with:

```sh
python -m f1fantasy.refresh_history
```

Only the updater can download missing completed sessions. Website publication
reads this file strictly and fails closed when required historical inputs are
missing. Every historical observation must precede the forecast cutoff. Current
prices, active roster, schedule and Statistics are still fetched afresh.

The separate **Refresh public history** workflow updates this file after races;
the Pages workflow does not rebuild raw FastF1 history. Existing completed racing
records are reused, so the updater only loads newly completed racing sessions.
For upstream corrections, remove the affected racing record and rerun the updater.
