# F1 Fantasy planner (V1)

Read-only recommendations for F1 Fantasy. Fetches the current race-week's public
Fantasy prices and roster for **every** run, then uses completed FastF1 results to
estimate qualifying, Sprint and race points. Fails when the next race's feed is
unavailable or the lineup cannot be verified.

## Install

Requires Python 3.11 or newer.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/f1fantasy prices
.venv/bin/f1fantasy recommend --races 3
```

The first recommendation uses a $100m budget. To plan transfers from your real
team, import its **current total spendable budget** (team value plus remaining
cash), five driver Fantasy IDs, two constructor Fantasy IDs and optional unused
carried transfer. IDs are printed by `prices`.

```sh
.venv/bin/f1fantasy init --drivers 1 2 3 4 5 --constructors 25 27 --budget 102.4 --carry 1
.venv/bin/f1fantasy recommend --races 3
```

Alternatively `f1fantasy init --import-file my-team.json` accepts:

```json
{
  "season": 2026,
  "budget": 102.4,
  "carry": 1,
  "drivers": ["1", "2", "3", "4", "5"],
  "constructors": ["25", "27"]
}
```

These are example IDs only; select actual active IDs from the live `prices`
output. The validated local team state is stored at `.f1fantasy/team.json`
(ignored by Git). Re-import it after applying changes on the Fantasy website.
Use `--allow-penalties` only if paying −10 points per extra transfer is acceptable.
Pass `--season YEAR` and `--state PATH` before the command to override defaults.

The optimizer considers five drivers, two constructors, budget, the 2× Boost,
net transfers, one-week carry-over and Sprint points. Future race prices are
assumed unchanged; re-run after every price update. This early forecast uses
classification and grid positions from FastF1. Official Fantasy overtakes,
Driver of the Day and constructor pit-stop bonuses are not predicted, so
projected points are approximate. Sprint qualifying earns no separately
modeled Fantasy points. It never logs into or changes an F1 account.

Rules: [F1 Fantasy FAQ](https://fantasy.formula1.com/en/faqs),
[2026 game rules](https://fantasy.formula1.com/en/game-rules).
