# Pitwall

**Season-long strategy planning for F1 Fantasy.**

Pitwall is a static website where you enter your F1 Fantasy teams and plan the rest of the season. It jointly optimises five drivers, two constructors, Boost, chip timing and net transfers for maximum predicted points under your budget.

## Features

- **Season-wide planning:** plans every remaining published round, not a rolling horizon.
- **Exact optimisation:** a mixed-integer optimiser (HiGHS WebAssembly) runs in a browser worker.
- **Independent teams:** create a blank team in Garage and save teams in your browser, with JSON import/export.
- **Detailed forecasts:** qualifying, Sprint and race projections, with [chronologically validated Fantasy modeling](docs/fantasy-model.md) adopted only where it beats both baselines.
- **Race Insights:** searchable driver/team cards and placement distributions, race and fastest-stationary-stop probabilities, plus real F1 championship point projections with simulation ranges.
- **Transparent strategy:** round-by-round changes, penalties, multipliers and chip effects.
- **Privacy-friendly:** no F1 login, server-side team storage or automatic submission required.
- **Companion CLI:** a Python CLI and official F1 Predict tooling (see [Predict commands](docs/predict.md)).

## Quick start

Requires Python 3.11+ and Node.js.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m f1fantasy.web_data
npm ci --prefix web
npm run dev --prefix web
```

Open the local URL printed by Vite.

## Using the website

1. In **Team Garage**, pick your seven selections from the asset registry.
2. Enter **team value plus cash**, free transfers and remaining chips.
3. Open **Strategy** to see transfer, Boost and chip directives, net score comparisons, the cumulative season trajectory and each round's selection breakdown.

Strategy updates automatically as you edit. Open **Race Insights** to select a remaining round, search drivers or teams by name, abbreviation or constructor, inspect placement predictions in the sidebar and explore championship projections. Observed points, real F1 predictions and Fantasy forecasts are separate; probabilities and ranges are explicitly uncalibrated. Final Fix is shown as a separate post-qualifying decision rather than given speculative pre-weekend points.

The interface follows [`DESIGN.md`](DESIGN.md), with a full-width Garage, compact mobile roster, bottom navigation, recorded round-price trends and coloured chip controls. Driver and car images come from the TracingInsights 2026 collection; venue photographs and circuit outline change with the selected round. Credits are in the footer.

See [website design and data boundaries](docs/website.md#design-and-accessibility) and [replacing images](docs/media.md).

## Data

Completed-session inputs ship in [`data/history.json`](data/README.md), so Pages builds never download raw FastF1 sessions. The **Refresh public history** workflow updates it daily or on demand, reusing completed race records. Normal publication still fetches current official prices, roster, schedule and Statistics. Racing forecasts are compared with chronological baselines before adoption; see [model evidence and measured limitations](docs/racing-model.md).

Neither workflow needs `F1_USERNAME` or `F1_PASSWORD`. FastF1's optional live-feed authentication warning is not a request for your credentials.

## Command-line interface

Install into the virtual environment and activate it (or call `.venv/bin/f1fantasy` directly):

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

Common commands:

```sh
f1fantasy prices                      # current roster and prices
f1fantasy recommend --races 3         # recommend for your connected team
f1fantasy recommend --team 2          # a specific team on the account
f1fantasy recommend --no-account --no-chips --races 3   # local preview
f1fantasy chips                       # chip planning
f1fantasy statistics                  # official Fantasy Statistics rankings
f1fantasy backtest --races 4 --show-points
```

Every command accepts `--format json` for versioned, machine-readable output. Prices are integer tenths of a million (`price_tenths_m`).

> Always check the Fantasy website's team-lock deadline. The session start shown by the CLI is not a verified lock time.

### Requirements

- Python 3.11+ and an internet connection (F1 Fantasy and FastF1 data).
- Optional: about 0.1–1 GB of disk for a three-season `preload` cache in compact mode.

### Documentation

| Topic                                                                                | Guide                                                      |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| Full CLI reference (recommend, transfers, chips, Final Fix, preload, backtest, JSON) | [docs/cli.md](docs/cli.md)                                 |
| Chip model                                                                           | [docs/chips.md](docs/chips.md)                             |
| Account integration and applying changes                                             | [docs/account-integration.md](docs/account-integration.md) |
| Scheduling                                                                           | [docs/scheduling.md](docs/scheduling.md)                   |
| F1 Predict commands and verification limits                                          | [docs/predict.md](docs/predict.md)                         |
| Website design and data boundaries                                                   | [docs/website.md](docs/website.md)                         |
| Replacing images                                                                     | [docs/media.md](docs/media.md)                             |
| Roadmap                                                                              | [roadmap.md](roadmap.md)                                   |

## Resources

- [F1 Fantasy rules](https://fantasy.formula1.com/en/game-rules) and [FAQ](https://fantasy.formula1.com/en/faqs)
- [F1 Fantasy public schedule feed](https://fantasy.formula1.com/feeds/v2/schedule/raceday_en.json)
- [F1 Fantasy Statistics](https://fantasy.formula1.com/en/statistics)
- [FastF1 documentation](https://docs.fastf1.dev/)
- [F1 Predict rules](https://f1predict.formula1.com/en/game-rules) and [FAQs](https://f1predict.formula1.com/en/faqs)
