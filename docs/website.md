# Pitwall: static remaining-season planner

## What users can do

- Save three independent teams locally, name them, and import/export JSON.
- Enter the original race-week five drivers/two constructors, total budget
  (roster value plus cash), one carried transfer, initial-team status and chips.
- Allow paid net transfers only when their predicted gain justifies their cost.
- Optimize all remaining published rounds jointly. Inspect each round's changes,
  chip, 2×/3× drivers, cost, transfer penalty, carry and per-selection Q/S/R points.
- Use the price-focused registry to select drivers/constructors and inspect their
  actual recorded round-price changes. Points are shown in Strategy, not Garage.
- Continue an already active chip; active Limitless requires the original seven
  it will restore. Its temporary scoring roster and durable transfer baseline
  remain distinct. An initial Limitless restores the entered current roster.

Final Fix is displayed and explained, but not spent by a speculative pre-weekend
season optimization. It requires known elapsed points and remaining-session
eligibility in the actual post-qualifying window; the optional account CLI retains
that workflow. A season plan's projected total excludes hypothetical Final Fix
benefits. Future prices are held constant and no future race result is used as
an input. Update your manual team after a race; the browser replans after edits.

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
−10 per extra transfer, considered only when worthwhile in the net-points season
objective, first-team unlimited changes,
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
CORS failure uses a labelled **published-snapshot preview** automatically.
It never says manual budget, transfer state or chip inventory are account-verified.

Published data expires after six hours. Started or locked target weekends are
rejected; old-price fallback is not used. Failed upstream generation publishes an
unavailable manifest instead of silently presenting prior data as fresh. CI or
deployment failures can leave an older site online, but browser expiry still
blocks its data. Truly live verified account recommendations on a static Pages
origin need a separately deployed backend/proxy, which is not part of this site.

With seven selections, edits are debounced for 700 milliseconds before planning.
Further edits terminate the old worker; replies from obsolete work are discarded.
Calculations stay on the current page and do not move focus or scroll position.
The foreground page checks for a new publication every minute and when returning
to a backgrounded tab. Only a changed publication or changed team requires a new
solve. Missing/expired data clears the old plan and retries on a later refresh;
the six-hour limit and readable official-feed conflicts still stop planning.

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

V5 follows the user-supplied root `DESIGN.md`: Grand Prix Broadsheet,
self-hosted Inter, paper/ink/vermilion, hairline borders, restrained corners and
tabular figures. The exact Stitch project `6085770950590244465` references are:

- `8c7013a0b2254d19b7293cfe93cdd18b`: Visual Strategy & Season Breakdown.
- `202e82a082484112bf664e97e619b45f`: Visual Team Garage.
- `999e252f73234cf290cbc36dfbef6bd4`: Visual Race Simulation & Insights.
- `67e915462af84cd2869006d89d411a16`: Strategy (Mobile).
- `215de48ec39247258ab4a50bc1803b96`: Team Garage (Mobile).

Strategy includes an actual circuit-coordinate outline, transfer/Boost/chip directives,
next-round net score comparison, cumulative Fantasy trajectory and selectable
round details. The reference is explicitly the unchanged roster with best 2×
and no chips; it is not a league benchmark or a do-nothing active-chip forecast.
Autopilot shows scenario-dependent extra points rather than a fixed winner.

The Garage retains `pitwall-teams-v1` storage and JSON import/export. Settings
are on the main page rather than a sidebar. Five portrait cards, two wide car
cards and the four-column registry follow the supplied Visual Garage layout.
Free transfers are selected explicitly (two, three with carry, or unlimited for
a new team). The removed new-team/completed/paid checkboxes are replaced by this
single control and a fixed net-points policy: extra transfers always cost −10.
Chip icons are coloured when available and grey when marked used; toggles do not
activate anything on the official game. An active chip is still configured in
the advanced section. There are no manual Calculate, Recalculate, Refresh or
snapshot-consent controls. Zero current swaps can be optimal, with later planned
changes explained. Chip state is shown by colour and accessible pressed-state
labels rather than repetitive Available/Used text. Redraws do not re-scroll to
the registry hash anchor; automatic completion never changes the selected page.

All 33 current assets have locally hosted 2026 images from the requested
`TracingInsights/2026` collection, matched by current constructor and driver TLA.
Headshots are preferred; a missing headshot uses the matching upper-body cutout.
Transparent car sideviews are retained. The upstream repository uses Apache-2.0
and identifies Formula 1 as the image source; these images are not labelled
Creative Commons. The exact commit, original CDN URL and transformations are
recorded in the footer and `web/public/media/ATTRIBUTION.json`. The five remaining
venue photographs have separate Commons licences and archival dates. Circuit
outlines use the MIT-licensed `bacinger/f1-circuits` coordinates. Both venue photo
and circuit change with the selected round; unknown circuits are unavailable.
See [media replacement and provenance](media.md) for both importers and crops.

Sparklines use the latest four available official round-price observations in
`data/history.json`, followed by the freshly verified current price. These are
not intraday quotes or price forecasts. Missing history shows an unavailable
label rather than a synthetic trend. Historical prices do not replace current
market verification or change the constant-future-price optimizer assumption.

Forecasts is explicitly Coming soon. Real race probabilities, pit-stop and FIA
championship predictions remain V6; weather remains V8. The mockups' sample
confidence, weather, league rankings and lock countdowns are not measurements.

The large preview banner is removed; the footer retains the price-check time,
six-hour expiry, live/snapshot status and image credits. Inputs and chip controls
are labelled; keyboard focus, skip navigation and reduced-motion preferences
are supported. Charts have textual values/accessible descriptions and signed
point tables. Tables and round cards scroll within their regions on narrow
screens; the page itself should not scroll horizontally. There is no external
analytics or font request. Hash navigation and relative assets support Pages
repository paths without a server-side routing rewrite.

The prior Dockerfile/Compose/bootstrap and container-only tests were removed;
existing private host session directories were not deleted.
