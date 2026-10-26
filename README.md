# F1 Fantasy planner

This Python CLI recommends an F1 Fantasy team of five drivers and two constructors, chooses a 2× Boost driver, and plans transfers within your budget. It estimates qualifying, Sprint and race points from completed Fantasy scores and FastF1 results. An optional historical preload adds lap-telemetry comparisons between similar circuits and teammates. It recommends changes for you to make; it does not sign in or submit a team.

## Requirements

- Python 3.11 or newer and an internet connection for F1 Fantasy and FastF1 data.
- Disk space for a local historical cache if using `preload`; expect roughly 0.1–1 GB for three seasons in the default compact mode (estimates vary by season and session coverage). Allow extra temporary space while one session loads.
- No F1 account is required for recommendations. You can manually import your existing team to plan transfers.

## Usage

From this repository, install into a virtual environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

Activation lets you type `f1fantasy` in zsh or bash. Without it, use `.venv/bin/f1fantasy` for every command.

### Recommend a team

```sh
f1fantasy prices
f1fantasy recommend --races 3
```

Each recommendation fetches the next race's **current Fantasy roster and prices**. With no imported team, it assumes a new team with a $100m starting budget. Output includes budget, qualifying/Sprint/race estimates, Boost, net transfers and their penalties. Future prices are assumed unchanged until the next run. Always check the Fantasy website's team-lock deadline; the session start displayed by the CLI is not a verified lock time.

The optimizer solves for the **maximum total predicted points across the selected races**, including Boost and transfer penalties; it does not discount later weekends. This is the maximum under the model's forecasts and fixed future-price assumption, not a guarantee of actual race results. The production solver is a mixed-integer optimizer, not an exhaustive enumeration of all teams.

If the next race-week feed is empty, you can preview with the last completed race's official prices:

```sh
f1fantasy recommend --races 3 --allow-old-prices
```

This is labelled **provisional** because upcoming prices and driver availability have not been verified. Re-run without the flag before applying a lineup.

The CLI also checks the current race-week roster's prices and season-point totals against the [official Fantasy Statistics page](https://fantasy.formula1.com/en/statistics). To browse that page's rankings in the terminal, use `f1fantasy statistics`. A provisional old-price preview cannot be checked against the upcoming roster.

### Plan transfers from your team

Find active Fantasy IDs using `f1fantasy prices` (or `prices --allow-old-prices` for a provisional list). Import your actual team, current spendable budget in millions (team value plus remaining cash), and any one carried transfer:

```sh
f1fantasy init --drivers ID1 ID2 ID3 ID4 ID5 --constructors TEAM1 TEAM2 --budget 102.4 --carry 1
f1fantasy recommend --races 3
```

Alternatively, `f1fantasy init --import-file my-team.json` accepts `{"season": 2026, "budget": 102.4, "carry": 1, "drivers": ["ID1", "ID2", "ID3", "ID4", "ID5"], "constructors": ["TEAM1", "TEAM2"]}`. The CLI validates IDs against the fetched roster and stores your team at `.f1fantasy/team.json`, which Git ignores. Re-import after making changes on the Fantasy website. The optimizer uses two free net transfers after your first race, at most one carried transfer, and only permits extra −10-point transfers with `recommend --allow-penalties`.

`f1fantasy clear-team` removes only the **locally imported** team; it works offline and does not change an F1 Fantasy account. After clearing, the next recommendation treats you as a new $100m team. Pass `--state PATH` **before** the command if you imported into a custom location.

### Preload history and compare forecasts

```sh
f1fantasy preload --seasons 3
f1fantasy preload --status
f1fantasy backtest --races 4 --lookback 5 --compare-telemetry
```

`preload` covers completed sessions in the current and previous two seasons and resumes already processed sessions. By default it saves compact, versioned telemetry features and small parsed FastF1 results, then removes each session's bulky parsed car/position data and HTTP responses after verifying the features. It keeps FastF1's smaller HTTP cache entries, especially the repeated schedule requests, to avoid its request limit. Missing sessions are reported. To try one session first: `f1fantasy preload --seasons 2 --year 2025 --round 20 --session Qualifying`. Use `--refresh` to rebuild selected features; that session's telemetry must then be downloaded again. If FastF1's request limit is reached, wait for it to reset and rerun the same command: saved sessions are reused. A full three-season preload is estimated to take around 2–5 hours depending on the connection and missing sessions, versus roughly 2–4 hours with the previous full cache. The old cache could use about 10–25 GB; compact storage is estimated at 0.1–1 GB after completion. These are estimates, not limits. This historical cache **never replaces** the fresh Fantasy price and roster fetch on recommendations.

The model uses recent current-season Fantasy scores, FastF1 classification and grid form, earlier visits to each venue, and—when preloaded—circuit similarity and teammate-relative telemetry pace. Missing telemetry leaves the results-based forecast in place. `backtest` compares its point errors on regular and Sprint weekends; `recommend --no-telemetry` shows the results-only alternative. Past information is cut off before the predicted weekend. Estimated points are uncertain, especially for future bonus awards and changing car performance.

Race predictions separate ordinary finishes from severe-negative outcomes (approximated from earlier Fantasy race penalties). Their chance is shrunk toward the current team and field history, and unusually high past race scores are capped when estimating typical finish points. Sprint scores are shrunk toward race form when only a few Sprints are available. Use `recommend --no-risk` to compare with the original averaging approach.

Current-season FastF1 form has more influence than previous-season form (4× versus 1×, with older history weighted 0.5×). Current-season official Fantasy points remain the main scoring signal; older same-circuit evidence has a smaller adjustment. These underlying form weights remain fixed; V2 learns a **conservative calibration blend** of the current forecast, the earlier race model and a last-three-race baseline.

### Train V2 calibration weights

```sh
f1fantasy train
f1fantasy train --format json | jq '.data.model | {active, trained_rounds, validation_rounds, test_rounds, metrics}'
f1fantasy recommend --races 3 --format json | jq '.data.calibration'
```

`train` fits on earlier finalized weekends, compares candidate weights on later validation weekends, then measures them on a final untouched block. It saves a versioned artifact under `.f1fantasy/models/`; rerunning with the same completed races reuses that artifact instead of retuning on the test block. Only a candidate that improves **both** validation and test MAE for a scoring component is activated; `recommend` then loads it automatically. `--no-trained` restores the fixed-weight forecast, and sparse Sprint samples retain the baseline. The CLI never uses a trained artifact to predict a historical weekend at or before its training cutoff.

The first live 2026 run used rounds 5–11 for fitting, 12–14 for validation and 15–17 for testing. It **did not promote** the candidate: driver race MAE was 11.33 (fixed) versus 11.37 (candidate) on validation, and 10.81 versus 10.95 on test. Constructor race MAE was also slightly worse. Consequently, recommendations still use the fixed model. V2 currently learns calibration weights, not the internal 4×/1×/0.5× feature parameters; richer feature training remains future work.

### Inspect scores and use JSON output

```sh
f1fantasy backtest --races 4 --lookback 5 --show-points
f1fantasy backtest --races 6 --compare-risk
f1fantasy backtest --races 4 --compare-telemetry --format json \
  | jq '.data.rows[] | {race: .event.name, driver_mae: .mae_points.drivers}'
f1fantasy recommend --races 3 --format json \
  | jq '.data.lineups[] | {race: .event.name, boost: .boost_driver_id, points: .expected_points}'
f1fantasy statistics --format json | jq '.data.entries | sort_by(.season_points) | reverse | .[:5]'
```

`--show-points` lists **predicted and actual qualifying, Sprint, race and total points for every driver and constructor** in each selected historical weekend. MAE means *mean absolute error*, measured in Fantasy points: e.g. a driver MAE of 9.6 means the average driver's weekend prediction missed their actual total by 9.6 points, regardless of direction. Constructor MAE uses only constructors; qualifying, Sprint and race MAEs each include both drivers and constructors. These session MAEs do not necessarily add up to the total MAE because prediction errors can cancel between sessions. `--races` selects how many recent finalized weekends to replay.

Each backtest also reports **signed bias** (predicted minus actual, so positive means overprediction) and driver race MAE versus a simple average of up to the previous three completed races. This baseline comparison uses the same drivers on each side. `--compare-risk` compares race and Sprint error with/without the severe-negative adjustment; `backtest --no-risk` selects the older method. Current racing errors remain significant, so small improvements over a few weekends should not be mistaken for proof of general accuracy.

Every V1 command (`init`, `clear-team`, `prices`, `statistics`, `recommend`, `backtest`, `preload`, including `preload --status`) accepts `--format json` after the command. Text remains the default. JSON success is one versioned document on stdout, with timestamps, warnings, data-source status and numeric point fields; prices use **integer tenths of a million** (`price_tenths_m`). Progress/logging goes to stderr. On failure the CLI exits nonzero and writes a JSON error to stderr, leaving stdout empty; a partial preload reports its unavailable sessions as JSON and exits nonzero. `jq` is optional and only needed for the examples above.

## Roadmap and data sources

- [Simplified roadmap](roadmap.md) — V1, the initial V2 trainer, planned V3 account automation and V4 F1 Predict.
- [F1 Fantasy rules](https://fantasy.formula1.com/en/game-rules) and [FAQ](https://fantasy.formula1.com/en/faqs) — roster, scoring, Boost, chips and transfers.
- [F1 Fantasy public feeds](https://fantasy.formula1.com/feeds/v2/schedule/raceday_en.json) — event schedule; the CLI also fetches race-week driver/constructor prices and historical Fantasy scores.
- [F1 Fantasy Statistics](https://fantasy.formula1.com/en/statistics) — independent current-price and season-point verification and terminal rankings.
- [FastF1 documentation](https://docs.fastf1.dev/) — session results, laps, car telemetry and weather.
- [F1 Predict rules](https://f1predict.formula1.com/en/game-rules) — separate game planned for V4.
