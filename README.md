# Pitwall

[![Publish season planner](https://github.com/RJDonnison/Pitwall/actions/workflows/pages.yml/badge.svg)](https://github.com/RJDonnison/Pitwall/actions/workflows/pages.yml) [![Refresh public history](https://github.com/RJDonnison/Pitwall/actions/workflows/history.yml/badge.svg)](https://github.com/RJDonnison/Pitwall/actions/workflows/history.yml) [![Fit model parameters](https://github.com/RJDonnison/Pitwall/actions/workflows/model-fit.yml/badge.svg)](https://github.com/RJDonnison/Pitwall/actions/workflows/model-fit.yml)

Pitwall plans F1 Fantasy teams across the remaining season. It is available as a static browser [app](https://rjdonnison.github.io/Pitwall) and a [Python CLI](docs/cli.md).

The browser stores up to three teams locally. It can suggest a next-round team, compare round-by-round changes and optimize the remaining published schedule in a Web Worker with HiGHS. Race Insights and F1 Predict are separate views built from the same point-in-time racing data.

## Features

### Season planning

- **Whole-season exact optimisation:** jointly plans drivers, constructors, Boost, chips and transfers across every remaining round, solved in-browser with HiGHS (WebAssembly)
- **Team Garage:** three independent teams, stored locally, with JSON import/export
- **Transparent strategy:** round-by-round transfers, penalties, multipliers and chip effects

### Models

- **Self-fitting forecasts:** qualifying, Sprint and race projections built from FastF1 session data
- **Validated before adoption:** a model is used only if it beats chronological baselines
- **Wether data** is included in the racing model

### Race Insights

- **Placement distributions** per driver and team, plus race and fastest-stop probabilities
- **Championship outlook** with simulation ranges
- **Track data, pit stop analysis and driver/team breakdowns**

### F1 Predict

- **Live question fetching** with EV-based point estimates and risk modelling

## Run the website locally

You need Python 3.11+ and Node.js 20.19+ or 22.12+.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m f1fantasy.web_data
npm ci --prefix web
npm run dev --prefix web
```

Open the URL printed by Vite. The data publisher needs network access. The built site only needs a browser with WebAssembly support.

## Data and limits

Completed-session inputs are stored in `data/history.json`; For more information see [data/README.md](data/README.md).

Forecasts are estimates, not guarantees. The project does not claim measured prediction accuracy, calibrated probabilities or complete support for malformed historical Predict feeds.

Driver and constructor images load directly from raw GitHub URLs in the season's TracingInsights collection. Pitwall discovers team-aware TLA matches from `images/manifest.json`; venue photographs use GitHub-hosted copies with their original credits. See [docs/media.md](docs/media.md).

Fantasy and Predict can roll into later seasons under unchanged game contracts. History retains the current season and two prior seasons; daily Actions prune older model inputs and first forecasts without downloading them again. Downloaded image copies are not included in the site build.

### Known gaps

- **Risk doesn't shape the plan.** The optimiser maximises expected points. The F1 Predict risk setting does not change season plans or team suggestions.
- **Optimal for the model, not for reality.** "Exact" means the solver finds the best plan for the predicted points.
- **Future weekends are sampled independently.** Streaks such as car development or reliability runs aren't modelled across rounds.
- **Final Fix** is shown as a post-qualifying decision with no pre-weekend points forecast.
- **Team lock times** aren't verified. Always check the Fantasy site's deadline.
- **No automatic submission.** You apply changes yourself.
- **History updates daily, not live.** Pages builds use the shipped `data/history.json` and don't download raw FastF1 sessions.
- **Depends on unofficial feeds.** Prices, roster and schedule come from public F1 Fantasy endpoints that can change without notice.

## Official resources

- [F1 Fantasy rules](https://fantasy.formula1.com/en/game-rules) and [FAQ](https://fantasy.formula1.com/en/faqs)
- [F1 Fantasy Statistics](https://fantasy.formula1.com/en/statistics)
- [FastF1 documentation](https://docs.fastf1.dev/)
- [F1 Predict rules](https://f1predict.formula1.com/en/game-rules) and [FAQ](https://f1predict.formula1.com/en/faqs)
