# Pitwall: static remaining-season planner

## What users can do

- Save independent teams locally, add a blank team with **New team**, name them, and import/export JSON.
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
it when clearing site data. Saved teams can belong to different people. Garage's
**New team** button adds and selects a separate blank roster without overwriting
existing teams. It starts with a $100m budget, all chips available, no carried
transfers and unlimited initial team selection; additional teams persist after reload.

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
Regular Boost uses the selected driver's portrait as the card background;
Autopilot shows the five eligible drivers instead. Next-round removals and arrivals
use separate OUT/IN rows with constructor, price and signed unboosted point contributions, in a bounded, keyboard-focusable
scroll region so long transfer lists do not stretch the adjacent directives.
The circuit inset uses a dark background. The slimmer masthead and matching pit-lane
logo/favicon follow the same broadsheet identity; registry action footers are compact,
and non-interactive recommended-team table rows have no hover affordance.
The race photograph and paper track/weather panel share one integrated hero border,
with the circuit inside that context panel on desktop. Mobile stacks the photo,
circuit and track/weather data vertically. The three desktop recommendation cards share a compact 340-pixel height;
transfers scroll within their card rather than stretching the row. Stacked mobile
cards keep their natural compact heights.
The logo opens Strategy; navigation contains Garage and Race Insights. Mobile hides
the budget header, and race breakdowns stay expanded at every size. Season cards
reuse the coloured chip icons, with stronger selected-card outlines.

Track specifications for the five remaining 2026 rounds use official Formula 1
circuit guides (length, race laps and race distance; sources remain in footer credits). Public
Open-Meteo daily forecasts add air-temperature range, maximum daily precipitation
probability and maximum wind over the weekend's UTC dates, with source, units and
retrieval time in the public dataset. Hero source links and the ISO date-range line
are omitted for a cleaner panel. These are air forecasts, not track temperatures or a probability
that the entire race is wet. Beyond the 16-day window, missing/invalid weather or
an API outage displays an unavailable state; it cannot prevent publication of valid
Fantasy forecasts. No browser API key or account credentials are involved. The optional
weather request runs with each two-hour public-data publication; weather is display
context only and does not influence scoring, selection or the optimizer. Unknown
circuits/seasons do not inherit another venue's specifications.

The Garage retains `pitwall-teams-v1` storage and JSON import/export. Settings
are on the main page rather than a sidebar. Five portrait cards, two wide car
cards and the four-column registry follow the supplied Visual Garage layout.
Registry cards carry their constructor colour and an unboosted next-weekend
Fantasy point estimate, with compact black Add/Remove controls. These estimates
include qualifying, Sprint when present, and race; they do not include Boost,
chips or transfer penalties. Search and type filters share a row, and import/export
sits alongside the already-active-chip settings.
Replace removes the selected asset and opens the registry with its driver/constructor
filter and search focused, ready for the replacement.
The latest next-race suggestion is saved in each local profile across page reloads
and new publications. Once its scheduled final session has ended **and** the next
round is published, Garage offers **Update local team** or **Discard suggestion**.
Update is an explicit confirmation that you followed that lineup: it copies the
seven selections, removes that round's spent chip, advances carried transfers,
clears the completed active chip and replans. Limitless copies its restored roster,
not the temporary uncapped picks, and clears carry. Stored cash is retained while
current roster prices determine the updated total budget. Check the budget and
transfer allowance against your official account, especially if your actual trades,
Final Fix or prices differed. Stale publications, inactive selections, invalid saved
data and unfinished weekends cannot update the profile. Other profiles and the
official Fantasy account are untouched; recommendations are never auto-adopted.
Selected registry cards use a two-pixel constructor-colour outline and subtle tint.
Registry sorting supports ascending/descending price, name, next-round unboosted
points and points per $m. Sorting composes with search and driver/constructor filters.
The compact 30-pixel Add/Remove visual retains an expanded 44-pixel touch hit area.
Free transfers are selected explicitly (two, three with carry, or unlimited for
a new team). The removed new-team/completed/paid checkboxes are replaced by this
single control and a fixed net-points policy: extra transfers always cost −10.
Chip icons are coloured when available and grey when marked used; toggles do not
activate anything on the official game. An active chip is still configured in
the advanced section. There are no manual Calculate, Recalculate, Refresh or
snapshot-consent controls. Zero current swaps can be optimal; the redundant
no-swap/first-future-change paragraph is removed. Chip state is shown by colour
and accessible pressed-state labels rather than repetitive Available/Used text. Redraws do not re-scroll to
the registry hash anchor; automatic completion never changes the selected page.

All 33 current assets have locally hosted 2026 images from the requested
`TracingInsights/2026` collection, matched by current constructor and driver TLA.
Headshots are preferred; a missing headshot uses the matching upper-body cutout.
Transparent car sideviews are retained. The upstream repository uses Apache-2.0
and identifies Formula 1 as the image source; these images are not labelled
Creative Commons. The exact commit, original CDN URL and transformations are
recorded in the footer and `web/public/media/ATTRIBUTION.json`. The five remaining
venue photographs have separate Commons licences and archival dates. Current circuit
sector maps use the official guide geometry; other outlines use the MIT-licensed
`bacinger/f1-circuits` coordinates. Portrait and car-image backplates are transparent.
Both venue photo and circuit always describe the next race, even while a future round's plan is
selected below; unknown circuits are unavailable.
See [media replacement and provenance](media.md) for both importers and crops.

Sparklines use the latest four available official round-price observations in
`data/history.json`, followed by the freshly verified current price. These are
not intraday quotes or price forecasts. Missing history shows an unavailable
label rather than a synthetic trend. Historical prices do not replace current
market verification or change the constant-future-price optimizer assumption.

Race Insights implements V6; weather's integration into the race model remains
V8. Mockup confidence, league rankings, track temperatures and lock countdowns are
not measurements. The footer mirrors Stitch's strategic-principle, optimizer,
forecasts and privacy sections while retaining actual data status and image credits.

The large preview banner is removed. The footer's compact `Price snapshot` label
shows the price-check time explicitly in UTC as plain text, without a dropdown.
Publication/expiry details remain available to assistive technology. A successful
direct check instead says `Live prices verified`. This is a
data-source disclosure, not a solver error. Footer headings/body copy use a consistent
hierarchy with the three bordered editorial column headings from Stitch, alongside
image credits. Inputs and chip controls
are labelled; keyboard focus, skip navigation and reduced-motion preferences
are supported. Charts have textual values/accessible descriptions and signed
point tables. Tables and round cards scroll within their regions on narrow
screens; the page itself should not scroll horizontally. There is no external
analytics or font request. Hash navigation and relative assets support Pages
repository paths without a server-side routing rewrite.

The prior Dockerfile/Compose/bootstrap and container-only tests were removed;
existing private host session directories were not deleted.

## V6 Race Insights

Unboosted Fantasy session forecasts now use the chronologically evaluated
[Fantasy feature model](fantasy-model.md) where its chronological group-specific
MAE beats both existing and recent-score baselines. Rejected/sparse groups retain
the existing estimator. This is separate from the real-F1 placement distributions;
publication exposes adoption evidence under `model.fantasy`.

The desktop/mobile page adapts Stitch project `6085770950590244465`, dashboard
`52730fb5dc454fce9b40080dd77c0495` and mobile `9f99673b1923479895259aaa89f2971a`:
photo-led dark race hero, translucent four-stat briefing, readable circuit sector map,
context tiles and a 7:5 Fantasy/championship workbench. A single selectable driver/
team deep dive replaces overlapping contender and podium-card sections. Team
colours identify entrants; qualifying, Sprint and race use ink, warm grey and
vermilion chart colours. Signed Fantasy bars retain negative session
components, and observed/expected championship points remain separate. Numeric
labels and full tables accompany the graphics. The downloaded Stitch design is
the visual reference; its illustrative confidence, weather effects, timings and
title odds are not published as data.

`web/src/track-guides.json` records the official Formula 1 guide and original
photo/map URLs for all five remaining 2026 circuits. Local WebP files preserve
the map annotations, including numbered turns and sector splits. The Mexico and
Interlagos guides published at the 30 October check also mark straight-mode and
overtake activation/detection areas: these are the 2026 replacement for DRS.
Las Vegas, Lusail and Yas Marina maps do not yet annotate activation zones.
Both Strategy and Insights use the same clean three-sector SVG rather than
shrinking dense map labels; the Insights link opens the detailed official map.
Repeated ticker/badges and the verbose
activation-zone paragraph are removed. Full-size maps
and original source links are accessible. Lap records, first-GP years and circuit
descriptions follow the same season-specific official guides; later seasons
do not silently inherit these records. Footer credits retain original asset URLs.
The SVG surfaces are extracted from official coloured track lines, joining short
gaps obscured by sector text and removing labels/backgrounds. S1/S2/S3 have a compact
legend; no activation positions are inferred. Regenerate from local source maps with
`python -m f1fantasy.circuit_maps`, then format `web/src/sector-maps.json` with Prettier.

The selected round also owns its weather briefing. Validated Open-Meteo daily
air-temperature ranges, precipitation probabilities and maximum 10 m wind speeds
are published alongside the weekend aggregates. Values retain units, UTC dates,
fetch time and attribution in the export and site source information. The repeated
weather footer is removed; Open-Meteo attribution remains in the site footer.
Out-of-horizon/missing weather stays unavailable;
air temperature is not labelled track temperature and weather remains display-only.

`f1fantasy.insights` adds an optional `insights` object to the existing schema-1
forecast publication. It uses 4,000 seeded joint racing draws per remaining round,
the chronologically selected racing model and earlier cached telemetry (see
[model evaluation](racing-model.md)). A single cutoff, the
earlier of publication time and first target session, applies to racing records,
telemetry features and pit-label completion/publication dates across the horizon.

Driver probabilities cover GP win, podium, pole, top ten and not classified, plus
Sprint outcomes on Sprint weekends. A team probability means **at least one car**,
calculated from joint samples rather than adding individual probabilities. Not
classified does not necessarily mean mechanical retirement. Stationary-service
timing and shared stop-opportunity models must pass chronological baselines;
otherwise decayed finalized official winner labels with a one-win-per-team prior
remain explicit. Names/aliases join sources rather than cross-game IDs; sources,
counts remain visible, with dated evidence retained in the publication. Transit
times are never service times.

Race probabilities precede the deep dive. Its searchable participant grid replaces
the participant dropdown: search by name, team or driver code, then choose a
portrait/car card showing unboosted Fantasy points and expected race position.
Selected predictions occupy a right-hand sidebar on desktop and stack beneath
the grid on mobile; selecting a mobile card brings its predictions into view.
Search text and selection survive round changes. The page has no collapsible
sections or Historical record section; the round and probability-outcome selectors
remain. Portraits/car images accompany names in both the deep dive and Strategy's
race breakdown. Qualifying, race and Sprint distributions come from the same joint
draws as the overview: classified-position bins plus NC sum to one. Expected
position and central 80% ranges condition on classification and are uncalibrated.
Teams show each current driver's distribution, not a fictitious constructor race
finishing position. Team outcome probabilities remain at-least-one-car events.
The title-contender horizon remains a single chart, and comparison panels use
aligned bounded lists rather than mismatched long columns.

Historical exports enumerate included rounds against completed scheduled rounds.
GP weekends, individual car entries, classifications, wins, podiums, poles and
Sprint wins/entries are separate. The current archive covers all 18 completed
2026 GPs plus all 24 GPs in each of 2024 and 2025; partial seasons are explicitly labelled.
Historical participants remain in those exports outside the current roster, and past team
points retain their recorded constructor. Observed real F1 points sum FastF1
Race/Sprint session points, not Fantasy scores or an independently reconciled FIA
standings feed; subsequent non-session championship adjustments may differ.

Championship projections require complete current-season Race, qualifying, Sprint
and session-point coverage. Observed points plus simulated remaining GP points
(25–18–15–12–10–8–6–4–2–1) and Sprint points (8–1) yield expected final points,
assuming full-distance scoring and no fastest-lap bonus. Inactive participants
retain earned points and receive no future starts. Current roster and historical
form remain fixed; future weekends are drawn independently without feeding
simulated results back into form. Constructor intervals sum both cars in each
sample before computing quantiles. Central 80% ranges are **uncalibrated scenario
ranges**, not confidence scores. Expected-point order is not official countback
ranking or a title-odds model.

Championship Horizon shows only mathematically eligible title contenders. Each
entrant's maximum is observed points plus winning every remaining GP and Sprint
(constructors take the best possible finishes of their current cars, up to a 1–2).
An entrant whose ceiling is below the current leader's observed points is removed.
At equal points, the entrant's best possible GP finish countback must not lose to
an existing leader's countback; Sprint wins do not decide that countback. Exact or
insufficiently observed countback ties remain eligible. The chart discloses hidden
entrants, and the table shows maximum possible final points separately from expected
points. This eligibility uses the same published schedule, recorded session points,
full-distance scoring and fixed-roster assumptions as the projections, rather than
rejecting someone because a finite simulation produced no wins. Eliminated entrants
remain in the publication and historical records; their earned points are preserved.

The expandable Fantasy table separately shows unboosted Q/S/R predictions and
weekend totals, excluding chips and transfer penalties. Insights needs no complete
Garage team. Missing Insights does not block valid Fantasy forecasts. Six-hour
freshness and price verification still apply. Model, seed, samples, cutoff and
sources are disclosed. V7 question recommendations, V8 weather modeling and V9
calibrated accuracy remain planned.
