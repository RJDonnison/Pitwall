# Pitwall: static remaining-season planner

## What users can do

- Save three independent teams locally, name them, and import/export JSON.
- Enter the original race-week five drivers/two constructors, total budget
  (roster value plus cash), one carried transfer, initial-team status and chips.
- Allow paid net transfers only when their predicted gain justifies their cost.
- Optimize all remaining published rounds jointly. Inspect each round's changes,
  chip, 2×/3× drivers, cost, transfer penalty, carry and per-selection Q/S/R points.
- Compare every active driver/constructor's forecasts in the searchable grid.
- Continue an already active chip; active Limitless requires the original seven
  it will restore. Its temporary scoring roster and durable transfer baseline
  remain distinct. An initial Limitless restores the entered current roster.

Final Fix is displayed and explained, but not spent by a speculative pre-weekend
season optimization. It requires known elapsed points and remaining-session
eligibility in the actual post-qualifying window; the optional account CLI retains
that workflow. A season plan's projected total excludes hypothetical Final Fix
benefits. Future prices are held constant and no future race result is used as
an input. Re-plan after each race or price/roster/budget/chip change.

No passwords, cookies, account identifiers or users' teams are sent to a server.
Local storage is browser/origin-specific; export a team to move devices or preserve
it when clearing site data. Three team profiles can belong to different people.

## Exact browser optimization

`web/src/optimizer.js` ports the Python mixed-integer model to HiGHS WebAssembly
in a dedicated worker, with a 90-second exact-solve limit. A non-optimal/time-limited
result is rejected rather than shown as optimal. A cancellation or input/profile
change terminates the worker and invalidates old asynchronous replies.

Constraints cover the full seven selections, budget, selected driver-only 2×,
distinct 3×, exact net incoming transfers, two free plus at most one carry,
−10 per explicitly allowed paid transfer, first-team unlimited changes,
once-per-season/one-chip-per-round eligibility, capped Wildcard and uncapped
temporary Limitless with restoration and carry reset. Autopilot values the best
selected **whole-weekend** driver within correlated empirical scenarios. No
Negative uses official category-adjusted uplifts for drivers, constructors and
Boost, not a clamp on net session totals. Chips absent from historical evidence
are disabled with an explanation rather than assigned invented values.

Browser tests compare objectives with the existing Python solver for every
pre-weekend chip, Sprint scoring, carry and paid transfers, plus chronological
input rejection. A conditional optimum is not a guarantee about actual points.

## Public data and freshness

`python -m f1fantasy.web_data` freshly verifies official Fantasy roster/prices and
Statistics using the existing Python adapter, computes pre-weekend estimates for
every remaining round, and publishes `web/public/forecast.json`. It exports only
public fields; account code, login sessions and private team files are not read.
The forecast file is ignored by Git and regenerated for each deployment.

Historical inputs are versioned separately in `data/history.json`: compact public
race classifications/championship points, Fantasy session scores, calendar
metadata and pre-weekend telemetry features. The publisher reads this dataset
strictly: it cannot fall back to a raw FastF1 download when an entry is missing.
This avoids a cold-cache multi-season download during deployment. The separate
**Refresh public history** action runs daily/manual with a longer time budget,
loads newly completed racing sessions, validates forecast coverage, and commits
only the public dataset. Its successful completion triggers Pages publication.
Run `python -m f1fantasy.refresh_history` locally for the same update.

No Formula 1 account credentials are required for these completed-session
inputs. FastF1 may log an optional live-feed authentication warning in the
updater and continue anonymously. An actual data error is handled separately;
it does not justify adding personal F1 login secrets to a static website.

The official Fantasy feeds currently return no browser cross-origin permission.
A Pages site cannot bypass that with client JavaScript or a secret embedded in
the bundle. Before **every** solve the site re-fetches the publication and attempts
fresh official roster, price, Statistics and schedule/lock checks. A successful
check detecting changed prices/roster or a locked event stops planning. A network/
CORS failure permits only an explicitly consented, labelled **snapshot preview**.
It never says manual budget, transfer state or chip inventory are account-verified.

Published data expires after six hours. Started or locked target weekends are
rejected; old-price fallback is not used. Failed upstream generation publishes an
unavailable manifest instead of silently presenting prior data as fresh. CI or
deployment failures can leave an older site online, but browser expiry still
blocks its data. Truly live verified account recommendations on a static Pages
origin need a separately deployed backend/proxy, which is not part of this site.

## Run and check locally

Requires Python 3.11+, Node 24+ and network for data generation; the deployed
website only needs a WebAssembly-capable browser.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m f1fantasy.web_data
npm ci --prefix web
npm run dev --prefix web
```

```sh
.venv/bin/python -m pytest
npm test --prefix web
npm run build --prefix web
npm run preview --prefix web
```

`npm test` invokes the installed Python package for solver parity. It prefers the
repository `.venv/bin/python`, otherwise `python3`; `PYTHON` selects another
executable. `--no-telemetry` on the publisher explicitly uses the base forecast.
No example predictions or stale price snapshot are substituted for missing data.

## GitHub Pages

1. Push the repository to GitHub, with `main` as the publishing branch. Repository
   settings/permissions must allow Actions and Pages.
2. Set **Settings → Pages → Build and deployment → Source → GitHub Actions**.
3. Run **Actions → Publish season planner → Run workflow**, or push to `main`.
4. Open the deployment URL from the `github-pages` environment. Normally it is
   `https://USERNAME.github.io/REPOSITORY/`; Vite's relative base supports a project
   path and custom-domain root without code changes.

`.github/workflows/pages.yml` installs/tests both runtimes, uses the committed
historical dataset, publishes fresh inputs, builds `web/dist`, uploads a Pages artifact
and deploys using GitHub's Pages/OIDC permissions. No authentication cookie,
password, token secret or user-team upload is required. It runs on push, manual
dispatch and every two hours; schedules can be delayed/disabled by GitHub, so
freshness is enforced in the browser as well. A year with no published roster or
no upcoming round produces the unavailable screen until verified data returns.

The deployment URL is reported by the `github-pages` environment after a
successful workflow run.

## Design and accessibility

The ice-blue/navy pit-wall layout uses self-hosted Barlow/Barlow Condensed,
compact score tables, explicit preview state, labelled inputs and chip controls,
visible keyboard focus, reduced-motion handling and responsive stacked sections.
Tables can scroll within their own region on narrow screens; the page itself
should not scroll horizontally. There is no external analytics or font request.
The prior Dockerfile/Compose/bootstrap and container-only tests were removed;
existing private host session directories were not deleted.
