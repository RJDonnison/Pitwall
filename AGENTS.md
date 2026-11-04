# F1 Fantasy project instructions

## Purpose

This repository powers Pitwall, a command-line and browser planner for official F1 Fantasy and F1 Predict. The Python package collects and validates live game data, produces chronological racing and Fantasy estimates, optimizes teams and Predict answers, and optionally reads or updates an authenticated account. The Vite site consumes generated publications and performs its Fantasy optimization in the browser.

## Project map

- `src/f1fantasy/` contains the Python package, `f1fantasy` CLI, data contracts, forecast models, optimizers, publication jobs, schedulers and optional account automation.
- `web/src/` contains the browser interface, publication readers, local team state, visual assets and the browser optimizer. Browser tests are in `web/test/`.
- `tests/` contains the Python test suite. Prefer a focused test file while diagnosing a failure, then run the broader relevant checks once the change is complete.
- `data/` contains committed public history, fitted model settings, evaluation reports and the first-publication forecast archive. See `data/README.md` before changing or regenerating an artifact.
- `.github/workflows/` refreshes public history, gates fitted model changes, builds the generated publications, runs Python and browser checks, and deploys GitHub Pages.
- `docs/` contains user-facing CLI and media documentation. Keep commands and product claims consistent with the implementation and configuration.

## Verified commands

Run these from the repository root:

```sh
python -m pip install -e '.[dev]'
python -m pytest
npm ci --prefix web
npm test --prefix web
npm run build --prefix web
npm run format --prefix web
```

Install `.[account]` as well when working on Playwright account integration. The package requires Python 3.11 or newer. Use `f1fantasy --help` for the installed CLI. The data artifact commands are listed in `data/README.md`.

## Data and safety rules

- Treat Fantasy prices as live data: fetch them anew for every recommendation; fail if prices or roster data cannot be verified.
- Account for both sprint and regular weekends, the full seven selections, the 2× Boost, the budget, and net transfers.
- Historical model inputs must precede the predicted weekend. Do not use current weekend results as predictions.
- Keep generated publications honest about freshness. A carried-forward forecast must retain its original generation time and state why a refresh was unavailable.
- Keep public artifacts free of credentials, cookies, private teams and raw telemetry. Preserve source and licensing notes when data or media provenance changes.
- Authenticated writes must fail closed when identity, roster, prices, lock state or an exact remote deadline cannot be verified. Preserve private file permissions, operation locks, durable journals, recovery checks and post-write readback.
- Regenerate committed data with its owning module or workflow. Do not hand-edit results to improve a metric, and do not assume an artifact is automatically pruned without checking its writer.
- Public history and first forecasts retain the selected season and previous two seasons. Use `python -m f1fantasy.prune_history` for offline pruning; keep all-time Predict winner facts. Never reintroduce removed downloaded media into Actions or the site build: images use raw upstream or pinned GitHub URLs, with attribution retained locally.
- The user requested a commit after each completed feature. Check status, diff and recent log before every commit, stage only intended files, and run relevant checks.
