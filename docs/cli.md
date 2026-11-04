# CLI reference

Install the package in a Python 3.11+ virtual environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

## Prices and recommendations

```sh
f1fantasy prices
f1fantasy recommend --no-account --no-chips --races 3
```

Each recommendation fetches current Fantasy roster and price data again. It plans five drivers, two constructors and a 2x Boost under the budget. Output includes qualifying, Sprint and race estimates, net transfers and penalties. Future prices remain unchanged within the hypothetical plan.

Connected account mode refreshes the chosen team before planning:

```sh
f1fantasy account connect --team 1
f1fantasy recommend --races 3
f1fantasy recommend --team 2 --races 5
```

`--team` selects an account team for a read-only recommendation. It does not change the team bound to `account apply` or scheduling.

If the next roster has not been published, `--allow-old-prices` can produce a clearly labelled provisional local preview:

```sh
f1fantasy recommend --no-account --no-chips --races 3 --allow-old-prices
```

Do not apply that preview. Run the command again without the flag after the upcoming roster and prices are available.

## Import a local team

Find current asset IDs with `f1fantasy prices`, then import the seven selections and total budget. Budget means team value plus cash.

```sh
f1fantasy init \
  --drivers ID1 ID2 ID3 ID4 ID5 \
  --constructors TEAM1 TEAM2 \
  --budget 102.4 \
  --carry 1
```

You can also use `f1fantasy init --import-file my-team.json`:

```json
{
  "season": 2026,
  "budget": 102.4,
  "carry": 1,
  "drivers": ["ID1", "ID2", "ID3", "ID4", "ID5"],
  "constructors": ["TEAM1", "TEAM2"]
}
```

The default state file is `.f1fantasy/team.json`, which is ignored by Git. Reimport it after changing the official team. An established team has two free transfers and can carry one unused transfer, for a maximum of three on the next weekend. Extra transfers cost 10 points and require `--allow-penalties`.

`f1fantasy clear-team` removes only the local import. It works offline and never touches the official account. Put global `--state PATH` before the command when using another state file.

## Chips

Chip planning is enabled by default for connected recommendations and `account apply`. Use `--no-chips` to prevent new chip use. An already active chip still affects scoring.

Local imports can include `available_chips`, `completed_first_weekend` and an optional `chip_reserve` map. Valid names are `autopilot`, `x3`, `no_negative`, `wildcard`, `limitless` and `final_fix`.

```sh
f1fantasy chips
f1fantasy recommend --races 3
f1fantasy recommend --chip x3 --chip-reserve limitless=90 --races 3
```

The optimizer permits one chip per weekend and each chip once per season. Wildcard removes transfer penalties but keeps the budget. Limitless temporarily removes the budget, restores the saved roster afterward and clears carry. x3 and the normal 2x Boost must use different drivers.

## Account commands

```sh
.venv/bin/python -m pip install -e '.[account]'
f1fantasy account connect --team 1
f1fantasy account show --format json
f1fantasy recommend --races 3
f1fantasy account apply --races 3
f1fantasy account audit --format json
```

The browser launcher checks `PLAYWRIGHT_CHROMIUM_PATH`, then `chromium` or `chromium-browser` on `PATH`, then a Playwright browser. Sign in and complete MFA yourself in the dedicated profile. Python does not collect the password.

Private state defaults to `$XDG_STATE_HOME/f1fantasy/account` or `~/.local/state/f1fantasy/account`. Use global `--account-dir PATH` before the command to choose another directory. Do not place a normal browser profile there.

`account apply` refreshes the account, event, roster, prices, Statistics, budget, transfer cost and chip eligibility. It checks official lock flags before every write and requires a matching read-back afterward. A save and chip activation can be separate requests, so the journal records each step and blocks blind retries after an uncertain result.

## History and backtests

```sh
f1fantasy preload --seasons 3
f1fantasy preload --status
f1fantasy backtest --races 4 --lookback 5 --compare-telemetry
f1fantasy backtest --races 4 --show-points
```

`preload` processes completed sessions from the current and previous seasons and resumes work it already saved. Compact mode keeps derived telemetry features and small parsed results while removing bulky session data after verification. Missing telemetry leaves the results-based forecast in place.

Backtests use only information before each historical weekend. `--show-points` lists predicted and official qualifying, Sprint, race and total Fantasy points. The output is evaluation evidence, not a guarantee for a future weekend.

## JSON output

Every command accepts `--format json` after the command or account action. JSON success is one versioned document on standard output. Logs go to standard error. Failures exit nonzero, write a JSON error to standard error and leave standard output empty.

Prices use integer tenths of a million under `price_tenths_m`. `jq` is optional.
