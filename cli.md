# CLI reference

Detailed usage for the `f1fantasy` command-line tool. For a quick overview, see the [README](../README.md).

## Recommend a team

```sh
f1fantasy prices
f1fantasy recommend --races 3
```

Each recommendation refreshes your connected team and fetches the next race's current Fantasy roster and prices, with chip planning enabled. Connect first with `account connect --team NUMBER` (see [Account](#account)). For local planning use `recommend --no-account`; without a chip inventory also add `--no-chips`. With no imported team in local mode, a new team with a $100m budget is assumed.

Output includes budget, qualifying/Sprint/race estimates, Boost, net transfers and their penalties. Future prices are assumed unchanged until the next run.

Recommend separately for different teams on the connected account:

```sh
f1fantasy recommend --team 1
f1fantasy recommend --team 2 --races 5
f1fantasy recommend --team 3 --format json
```

`--team` is read-only and requires account mode. It does not reconnect or change the single team bound to `account apply` or CLI automation.

### Provisional previews

If the next race-week feed is empty, preview with the last completed race's prices:

```sh
f1fantasy recommend --no-account --no-chips --races 3 --allow-old-prices
```

This is labelled **provisional** because upcoming prices and driver availability are unverified. Re-run without the flag before applying a lineup.

The CLI also checks the current race-week roster's prices and season-point totals against the [official Statistics page](https://fantasy.formula1.com/en/statistics). Browse its rankings with `f1fantasy statistics`. A provisional preview cannot be checked against the upcoming roster.

## Plan transfers from your team

Find active IDs with `f1fantasy prices` (or `prices --allow-old-prices`). Import your team, current spendable budget in millions (team value plus cash), and any carried transfer:

```sh
f1fantasy init --drivers ID1 ID2 ID3 ID4 ID5 --constructors TEAM1 TEAM2 --budget 102.4 --carry 1
f1fantasy recommend --no-account --no-chips --races 3
```

Alternatively, `f1fantasy init --import-file my-team.json` accepts:

```json
{
  "season": 2026,
  "budget": 102.4,
  "carry": 1,
  "drivers": ["ID1", "ID2", "ID3", "ID4", "ID5"],
  "constructors": ["TEAM1", "TEAM2"]
}
```

IDs are validated against the fetched roster and stored at `.f1fantasy/team.json` (ignored by Git). Re-import after making changes on the Fantasy website. The optimiser uses two free net transfers after your first race, at most one carried transfer, and permits extra −10-point transfers only with `recommend --allow-penalties`.

`f1fantasy clear-team` removes only the locally imported team; it works offline and does not touch your F1 Fantasy account. Afterwards, `recommend --no-account --no-chips` treats you as a new $100m team. Pass `--state PATH` before the command if you imported to a custom location.

## Plan chips

Chip planning is on by default for `recommend` and `account apply`; use `--no-chips` to disable new chip spending. An already-active chip remains in effect. `recommend` and `chips` refresh your connected account by default; `--no-account` uses your local import.

For local chip planning, add to your import:

- `available_chips`: list of unused chip names
- `completed_first_weekend: true`: eligibility for Wildcard/Limitless
- `chip_reserve` (optional): name-to-points map

Chip names: `autopilot`, `x3`, `no_negative`, `wildcard`, `limitless`, `final_fix`. Autopilot, x3 and No Negative are available immediately. Local inventory is user-supplied.

```sh
f1fantasy chips
f1fantasy recommend --races 3
f1fantasy recommend --chip x3 --chip-reserve limitless=90 --races 3
```

The optimiser allows one chip per weekend and each once per season. It keeps 2×/3× drivers distinct, values Autopilot using each scenario's best whole-weekend selected driver, and uses official category-adjusted No Negative history including constructors and Boost. Wildcard keeps the budget cap; Limitless temporarily removes it, restores the original roster for later transfers, and clears carried transfers.

Saving costs beyond the horizon are explicit **heuristics**: Autopilot 15, x3 40, No Negative 25, Wildcard 20, Limitless 80 points. Override with `chip_reserve` or repeatable `--chip-reserve NAME=POINTS` (zero is allowed). Defaults become zero when the horizon reaches season end. Within-horizon timing is jointly optimised.

Empirical chip inputs use up to five completed same-format current-season weekends strictly before the forecast; missing common history fails closed. Official null-score weekends are excluded from the joint sample for all assets, and recommendations report contributing game days, sample counts and exclusions. See [chip model details](chips.md).

### Final Fix

Final Fix is re-evaluated separately after qualifying, once the server opens its window:

```sh
f1fantasy chips --final-fix --format json
f1fantasy account apply --final-fix
```

These commands refresh the account, official window and still-unscored session boundaries. The preview forecasts only the remaining Sprint/race sessions from pre-weekend inputs, preserves official accrued points, and considers one affordable replacement with inherited Boost. Apply re-verifies the original roster, retained points and window immediately before submission, then reconciles original and replacement entries on read-back. A closed window, another active chip or ambiguous scoring stops the action. If no replacement improves the forecast, it returns `unchanged` without consuming Final Fix.

An offline **provisional** input is also available:

```sh
f1fantasy chips --no-account --final-fix remaining.json --format json
```

The imported team needs `boost_driver_id` and an unused `final_fix`. Supply:

- `gameday_id`
- timezone-aware `window_open_utc` / `window_close_utc` enclosing now
- multiplier-adjusted `accrued_points`
- `remaining_sessions` (e.g. `["race"]`)
- `remaining_points` keyed by every active asset ID, each with numeric `qualifying`, `sprint` and `race` fields (elapsed sessions must be zero)

The preview labels your window and forecasts as unverified, preserves accrued points, inherits Boost on replacement and retains the original roster for restoration. It does not activate a chip.

## Account

```sh
.venv/bin/python -m pip install -e '.[account]'
f1fantasy account connect --team 1
f1fantasy account show --format json
f1fantasy chips
f1fantasy recommend --races 3
f1fantasy account apply --races 3
f1fantasy account audit --format json
```

The launcher uses `chromium` or `chromium-browser` from your PATH (including `/usr/bin/chromium` on Arch Linux). Set `PLAYWRIGHT_CHROMIUM_PATH` to override. If neither a system nor Playwright browser is installed, install one before connecting; system Chromium needs no Playwright download.

`connect --team 1` binds the official one-based team number. Sign in and complete MFA in the dedicated browser, then open My Team. No password is collected and the browser session persists. Private session, binding and journal storage defaults to `$XDG_STATE_HOME/f1fantasy/account` or `~/.local/state/f1fantasy/account`, outside the repository; override with global `--account-dir PATH` before the command. An exclusive lock prevents concurrent profile use. Expired sessions require reconnecting.

### Applying changes

`account apply` recomputes forecasts and checks live event, roster, prices, statistics, budget, net-transfer penalties and chip eligibility. Immediately before preparing a mutation it re-fetches the official session lock flags (and an explicit deadline, when available). Each save requires fresh read-back.

- `--chip NAME` forces a chip; `--no-chips` applies lineup changes without spending one.
- `apply_status: unchanged` means the lineup and Boost already match the recommendation.
- Output reports success or a nonzero failure; the offline audit records prepared, unknown and verified outcomes.
- On restart, apply reconciles any pending outcome before forecasting or writing again; uncertainty blocks further writes.

Combined transfers/Boost changes plus Autopilot, No Negative or x3 activation use the same command. Both steps are validated up front; the lineup is saved and read back **before the chip is spent**, then the chip is activated and read back. Each step re-checks the live lock and account state. These are separate server requests, not an atomic transaction. If the second step fails, the command reports the saved lineup and the incomplete chip step. Run `account apply` again to resume only an unsent step; a possibly sent chip activation is never blindly retried. Inspect progress with `account audit --format json`. Pending recovery runs before a new recommendation, even if planning flags change.

Repeating `account apply` after a completed chip activation checks the live team against the latest verified journal and returns the verified result if it still matches, without replanning or resubmitting.

To deliberately optimise and apply a new lineup with an already-active chip:

```sh
f1fantasy recommend --races 3
f1fantasy account apply --replan --races 3
```

The active chip cannot be cancelled, replaced or charged another saving cost, and pending recovery still takes precedence over `--replan`. Active Limitless edits use the ordinary transfer endpoint without reactivating the chip, and its pre-activation roster is saved durably for later planning. If Limitless was activated outside this tool and its restoration roster cannot be verified, planning is limited to the current weekend.

**Live verification:** combined transfer/x3 has been verified on Team 2. Final Fix's window was closed during development, so its successful mutation and non-x3 chip accounting remain live-unverified; every write still requires exact fresh read-back. The optional CLI daemon runs scheduled stages through the same account boundaries. See [account integration](account-integration.md) and [scheduling](scheduling.md).

## Preload history and compare forecasts

```sh
f1fantasy preload --seasons 3
f1fantasy preload --status
f1fantasy backtest --races 4 --lookback 5 --compare-telemetry
```

`preload` covers completed sessions in the current and previous two seasons and resumes already-processed sessions. By default it saves compact, versioned telemetry features and small parsed FastF1 results, then removes each session's bulky parsed car/position data and HTTP responses after verifying the features. FastF1's smaller HTTP cache entries (notably repeated schedule requests) are kept to avoid its request limit. Missing sessions are reported.

- Try one session first: `f1fantasy preload --seasons 2 --year 2025 --round 20 --session Qualifying`
- Rebuild selected features with `--refresh` (that session's telemetry is downloaded again).
- If FastF1's request limit is reached, wait for it to reset and rerun the same command; saved sessions are reused.

Estimates (not limits): a full three-season preload takes roughly 2–5 hours depending on connection and missing sessions, versus 2–4 hours with the previous full cache. Compact storage is roughly 0.1–1 GB, compared with 10–25 GB for the old cache. The historical cache never replaces the fresh Fantasy price and roster fetch on recommendations.

### Forecast model

The model uses recent current-season Fantasy scores, FastF1 classification and grid form, earlier visits to each venue and, when preloaded, circuit similarity and teammate-relative telemetry pace. Missing telemetry leaves the results-based forecast in place. `backtest` compares point errors on regular and Sprint weekends; `recommend --no-telemetry` shows the results-only alternative. Past information is cut off before the predicted weekend. Estimated points are uncertain, especially for future bonus awards and changing car performance.

Current-season FastF1 form is weighted 4× versus 1× for the previous season, with older history at 0.5×. Current-season official Fantasy points remain the main scoring signal; older same-circuit evidence has a smaller adjustment. These are fixed weights, not a self-trained model.

## Inspect scores and JSON output

```sh
f1fantasy backtest --races 4 --lookback 5 --show-points
f1fantasy backtest --races 4 --compare-telemetry --format json \
  | jq '.data.rows[] | {race: .event.name, driver_mae: .mae_points.drivers}'
f1fantasy recommend --races 3 --format json \
  | jq '.data.lineups[] | {race: .event.name, boost: .boost_driver_id, points: .expected_points}'
f1fantasy statistics --format json | jq '.data.entries | sort_by(.season_points) | reverse | .[:5]'
```

`--show-points` lists predicted and actual qualifying, Sprint, race and total points for every driver and constructor in each selected historical weekend. `--races` sets how many recent finalised weekends to replay.

MAE (mean absolute error) is measured in Fantasy points: a driver MAE of 9.6 means the average driver's weekend prediction missed their actual total by 9.6 points, regardless of direction. Constructor MAE uses only constructors; qualifying, Sprint and race MAEs each include drivers and constructors. Session MAEs do not necessarily sum to the total MAE because errors can cancel between sessions.

Every command accepts `--format json` after the command (after the action for `account`, e.g. `account show --format json`). Text is the default. JSON success is one versioned document on stdout with timestamps, warnings, data-source status and numeric point fields; prices are integer tenths of a million (`price_tenths_m`). Progress and logging go to stderr. On failure the CLI exits nonzero and writes a JSON error to stderr, leaving stdout empty; a partial preload reports its unavailable sessions as JSON and exits nonzero. `jq` is optional.
