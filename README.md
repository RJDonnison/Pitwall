# F1 Fantasy planner

This Python CLI recommends an F1 Fantasy team of five drivers and two constructors, chooses Boost and chips, and plans transfers within your budget. It estimates qualifying, Sprint and race points from completed Fantasy scores and FastF1 results. An optional historical preload adds lap-telemetry comparisons between similar circuits and teammates. An optional persistent-browser integration connects one account team and provides an explicit manual apply path with live read-back.

**Account integration is not yet live-verified.** The researched website exposes a countdown but no verified explicit lock timestamp, so `account apply` currently blocks writes when that evidence is missing. Final Fix has a provisional future-only preview; live activation is blocked pending its window/read-back contract. Scheduling is excluded from this build.

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

### Plan chips

Add optional fields to your team import: `available_chips` (a list of unused chip names), `completed_first_weekend: true` (eligibility for Wildcard/Limitless), and `chip_reserve` (an optional name-to-points map). Names are `autopilot`, `x3`, `no_negative`, `wildcard`, `limitless`, `final_fix`. Autopilot/x3/No Negative are immediately available. Local inventory is user-supplied; `--account` refreshes it remotely.

```sh
f1fantasy chips
f1fantasy recommend --chips --races 3
f1fantasy recommend --chip x3 --chip-reserve limitless=90 --races 3
```

The optimizer allows one chip per weekend and each once per season. It keeps 2×/3× drivers distinct, values Autopilot using each scenario's best whole-weekend selected driver, and uses official category-adjusted No Negative history including constructors and Boost. Wildcard keeps the budget cap; Limitless temporarily removes it, restores the original roster for subsequent transfers, and clears carried transfers.

Saving costs beyond the horizon are explicit **heuristics**: Autopilot 15, x3 40, No Negative 25, Wildcard 20, Limitless 80 points. Override with `chip_reserve` or repeatable `--chip-reserve NAME=POINTS`; zero is allowed. Defaults become zero when the horizon reaches season end. Within-horizon timing is jointly optimized. Empirical chip inputs use up to five completed same-format current-season weekends strictly before the forecast; missing common history fails closed. See [chip model details](docs/chips.md).

Final Fix is a separate **provisional** preview:

```sh
f1fantasy chips --final-fix remaining.json --format json
```

The imported team needs `boost_driver_id` and unused `final_fix`. Supply `gameday_id`, timezone-aware `window_open_utc`/`window_close_utc` enclosing now, multiplier-adjusted `accrued_points`, `remaining_sessions` (e.g. `["race"]`), and `remaining_points` keyed by **every active asset ID**, each with numeric `qualifying`, `sprint`, `race` fields. Elapsed sessions must be zero. The preview labels your window/forecasts as unverified, preserves accrued points, inherits Boost on replacement, and retains the original roster for restoration. It does not activate a chip.

Official null-score weekends are excluded from the empirical joint sample for all assets. Recommendations report contributing game days and sample counts plus excluded game days; no complete common history fails closed.

### Connect one account team and apply manually

```sh
.venv/bin/python -m pip install -e '.[account]'
.venv/bin/python -m playwright install chromium
f1fantasy account connect --team 1
f1fantasy account show --format json
f1fantasy chips --account
f1fantasy recommend --account --chips --races 3
f1fantasy account apply --races 3
f1fantasy account audit --format json
```

`connect --team 1` explicitly binds the official one-based team number. Sign in and complete MFA in the dedicated browser, then open My Team. No password is collected; the browser session persists. Set `PLAYWRIGHT_CHROMIUM_PATH` for a nonstandard executable. Private session/binding/journal storage defaults to `$XDG_STATE_HOME/f1fantasy/account` or `~/.local/state/f1fantasy/account`, outside the repository. Override with global `--account-dir PATH` **before** the command. An exclusive operation lock prevents concurrent profile use. Expired sessions require reconnecting.

`account apply` recomputes forecasts and checks live event, roster/prices/statistics, budget, net-transfer penalties, chip eligibility and actual deadline before a single-request mutation and fresh read-back. Add `--chips` or `--chip NAME` to select a chip. Text/JSON output reports success or nonzero failure; the offline audit records prepared/unknown/verified outcomes. On restart, apply reconciles a pending outcome before forecasting or writing again; uncertainty blocks further writes.

**Current live gates:** public research found no verified explicit lock timestamp, so missing deadline evidence blocks writes. Final Fix activation is blocked pending its authoritative window/read-back contract. Combined transfers plus Autopilot/No Negative/x3 activation are rejected because no atomic contract was established. Active chips currently block new CLI planning. Authenticated schemas, session restoration and saves still require verification with your session. See [account integration details](docs/account-integration.md). No daemon or scheduled submission is included.

### Preload history and compare forecasts

```sh
f1fantasy preload --seasons 3
f1fantasy preload --status
f1fantasy backtest --races 4 --lookback 5 --compare-telemetry
```

`preload` covers completed sessions in the current and previous two seasons and resumes already processed sessions. By default it saves compact, versioned telemetry features and small parsed FastF1 results, then removes each session's bulky parsed car/position data and HTTP responses after verifying the features. It keeps FastF1's smaller HTTP cache entries, especially the repeated schedule requests, to avoid its request limit. Missing sessions are reported. To try one session first: `f1fantasy preload --seasons 2 --year 2025 --round 20 --session Qualifying`. Use `--refresh` to rebuild selected features; that session's telemetry must then be downloaded again. If FastF1's request limit is reached, wait for it to reset and rerun the same command: saved sessions are reused. A full three-season preload is estimated to take around 2–5 hours depending on the connection and missing sessions, versus roughly 2–4 hours with the previous full cache. The old cache could use about 10–25 GB; compact storage is estimated at 0.1–1 GB after completion. These are estimates, not limits. This historical cache **never replaces** the fresh Fantasy price and roster fetch on recommendations.

The model uses recent current-season Fantasy scores, FastF1 classification and grid form, earlier visits to each venue, and—when preloaded—circuit similarity and teammate-relative telemetry pace. Missing telemetry leaves the results-based forecast in place. `backtest` compares its point errors on regular and Sprint weekends; `recommend --no-telemetry` shows the results-only alternative. Past information is cut off before the predicted weekend. Estimated points are uncertain, especially for future bonus awards and changing car performance.

Current-season FastF1 form has more influence than previous-season form (4× versus 1×, with older history weighted 0.5×). Current-season official Fantasy points remain the main scoring signal; older same-circuit evidence has a smaller adjustment. These are fixed weights, not a self-trained model.

### Inspect scores and use JSON output

```sh
f1fantasy backtest --races 4 --lookback 5 --show-points
f1fantasy backtest --races 4 --compare-telemetry --format json \
  | jq '.data.rows[] | {race: .event.name, driver_mae: .mae_points.drivers}'
f1fantasy recommend --races 3 --format json \
  | jq '.data.lineups[] | {race: .event.name, boost: .boost_driver_id, points: .expected_points}'
f1fantasy statistics --format json | jq '.data.entries | sort_by(.season_points) | reverse | .[:5]'
```

`--show-points` lists **predicted and actual qualifying, Sprint, race and total points for every driver and constructor** in each selected historical weekend. MAE means *mean absolute error*, measured in Fantasy points: e.g. a driver MAE of 9.6 means the average driver's weekend prediction missed their actual total by 9.6 points, regardless of direction. Constructor MAE uses only constructors; qualifying, Sprint and race MAEs each include both drivers and constructors. These session MAEs do not necessarily add up to the total MAE because prediction errors can cancel between sessions. `--races` selects how many recent finalized weekends to replay.

Every command accepts `--format json` after the command (after the action for `account`, e.g. `account show --format json`). Text remains the default. JSON success is one versioned document on stdout, with timestamps, warnings, data-source status and numeric point fields; prices use **integer tenths of a million** (`price_tenths_m`). Progress/logging goes to stderr. On failure the CLI exits nonzero and writes a JSON error to stderr, leaving stdout empty; a partial preload reports its unavailable sessions as JSON and exits nonzero. `jq` is optional and only needed for the examples above.

## Roadmap and data sources

- [Simplified roadmap](roadmap.md) — V1 status and future V2/V3 milestones.
- [F1 Fantasy rules](https://fantasy.formula1.com/en/game-rules) and [FAQ](https://fantasy.formula1.com/en/faqs) — roster, scoring, Boost, chips and transfers.
- [F1 Fantasy public feeds](https://fantasy.formula1.com/feeds/v2/schedule/raceday_en.json) — event schedule; the CLI also fetches race-week driver/constructor prices and historical Fantasy scores.
- [F1 Fantasy Statistics](https://fantasy.formula1.com/en/statistics) — independent current-price and season-point verification and terminal rankings.
- [FastF1 documentation](https://docs.fastf1.dev/) — session results, laps, car telemetry and weather.
- [F1 Predict rules](https://f1predict.formula1.com/en/game-rules) — separate game planned for V4.
