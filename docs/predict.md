# V4: official F1 Predict

Predict has its own questions, answers, payouts, boosted question, account identity,
deadlines, archive and jobs. Fantasy prices, seven-player selections, transfers
and once-per-season chips do not govern this game.

## Read-only recommendations

```sh
source .venv/bin/activate
f1fantasy predict questions --format json
f1fantasy predict recommend
f1fantasy predict recommend --simulations 10000 --format json
f1fantasy predict recommend --no-telemetry --no-archive
f1fantasy predict recommend --gameday 20
f1fantasy predict recommend --scope season
```

Questions are fetched anew from the official configured season: all ten question
IDs, option IDs, option-specific points, cardinality and open status must be
verifiable. Explicit future rounds require published questions. `--scope season`
addresses the separate season bonus, rather than changing ordinary round scoring.
Rules/FAQs were reviewed for **2026**; another season requires a new scoring-rule
review in the adapter instead of silently retaining old assumptions.

Recommendations include option names and IDs, probabilities, model provenance,
calibration state, projected points and unsupported questions. Unknown meanings,
unsupported multi-answer scoring and missing evidence produce a partial result
and nonzero exit. A partial result cannot be submitted. Recommendations themselves
never save answers to the website.

### Expected points and the model

Selecting the most likely answer is not always optimal: an option's expected
points are its probability multiplied by its official payout. Ordered podium
selection solves a distinct-driver assignment across P1/P2/P3. A selected driver
earns their listed points for any top-three finish, double those points for the
exact position, and zero otherwise. Expected points for a slot are the listed
payout multiplied by the sum of the driver's any-podium and exact-position
probabilities. The single question 2× Boost is assigned to the
largest expected unboosted question total.

Podium probability is not just an ordering tie-breaker: a driver with a lower
chance of the exact slot can still be the better pick because they are more
likely to finish somewhere in the top three. For example, with a 10-point payout,
an 80% podium chance and 30% exact-position chance yield **11 expected points**
before Boost. Three selected drivers finishing on the podium in entirely the
wrong order still earn their three listed payouts.

### Website risk preference

The Predict navbar has **Low (λ = 0.5)**, **Medium (0.25)** and **High (0.1)**
risk levels. Medium is the default; the browser remembers the selection locally.
Each question maximizes **Score = EV − λ × SD**, using points for both EV and SD.
Low risk penalizes dispersion most strongly; High risk remains mildly risk-averse.
Expected points remain visible separately from the risk score and standard deviation.

Single-answer payouts use `SD = |payout| × sqrt(p × (1 − p))`, including the
zero-point unsuccessful/no-award outcome. The ordered podium evaluates every legal
distinct-driver assignment using its joint simulated payout distribution: listed
points for any podium finish plus the same again for the exact slot. Its SD includes
covariance between the three picks, not a sum of driver SDs. Chronological calibration
mixes the joint raw and uniform distributions with the same weight as the marginals.
Missing joint evidence leaves that risk-adjusted question unsupported.

The question Boost doubles both EV and SD, so it goes to the highest unboosted
question score. This is a **question-level** decision objective; it does not claim
to minimize whole-sheet SD across correlated questions. All three profiles are
published from the same forecast run, and changing the dropdown needs no network
request. Older publications without these profiles await the next publication.
CLI/account recommendations retain their existing EV objective.

### Applicability elsewhere

- **Fantasy season plans, team suggestions, transfers and chips:** applicable, but
  must score the entire seven-selection team on shared weekend scenarios, including
  Boost, Autopilot, No Negative, restoration and deterministic transfer penalties.
  `web/src/season-range.js` already evaluates those joint outcomes. Individual SDs
  cannot be added because drivers and constructors share race outcomes. Across
  weekends, the existing range model assumes independent weekend blocks.
- **Optimizer work required:** the existing HiGHS model has a linear expected-points
  objective. The square root of joint portfolio variance requires a conic-capable
  mixed-integer optimizer or a verified outer-approximation procedure to guarantee
  an optimum. Simply subtracting per-driver SD would change the requested formula.
  The Predict dropdown therefore does not alter Fantasy plans or team suggestions.
- **Race Insights:** finishing probabilities and championship forecasts describe
  outcomes, not user preferences. Keep those probabilities unchanged; risk belongs
  in a points-based decision layer with an explicit payout and joint distribution.

### Forecast inputs and coverage

The deterministic simulation uses prior-smoothed historical qualifying and race
ranks, classification rates and joint weekend variation, optionally adjusted by
the existing cached telemetry model. Qualifying, Sprint qualifying, Sprint and
race sessions remain distinct; missing Sprint qualifying evidence cannot become
ordinary qualifying evidence. Head-to-head questions allow neither driver to
score when both fail to classify. Team-specific classified counts include only
the named teams. Championship questions accumulate earlier official Race/Sprint
points and simulated future outcomes with countback, not a current standings
endpoint that may contain future results.

Regular-round questions also cover named teams reaching Q2/Q3, counts of teams
reaching Q3 or scoring Sprint points, team weekend-points comparisons, British
points scorers/winners, new winners at a particular Grand Prix, maximum positions
gained, and championship leaders or weekend title-clinching. Explicit `Tied`
options receive tie probability; comparisons without one award neither team points
on a tie. Replaced drivers retain their earlier official points and countback,
without being simulated as active entries in the target weekend.

Safety Car/VSC deployment counts and early-lap windows, red flags and first-lap
completion use archived FastF1 race-control messages and official completed laps.
The seeded empirical model weights recent races with a 20-event half-life and a
half-observation categorical prior. Missing messages do not become zero events,
and unknown deployment laps are excluded from early-window estimates. This is an
uncalibrated historical-frequency model, not a claim that interventions can be
predicted from racing pace. Sporting nationality and past venue winners use
complete, sourced Jolpica records; birthplaces are not nationalities.

All historical sessions and telemetry precede the earlier of observation time and
the target's first session. Current-weekend results, public `Answer`, option result
`Position`, and the site's non-normalized `Chance` hints are excluded from features.
Fastest stationary-pitstop probabilities use earlier finalized official Predict
winners with publication-time checks; pit-lane transit time is not stationary-stop
time. Before the season's first usable official winner label, at least four
earlier measured OpenF1 stationary-stop events can ground the existing
lognormal/opportunity-bootstrap model, explicitly marked uncalibrated.
`python -m f1fantasy.refresh_history --season 2026` refreshes these compact race
observations, sporting facts and timing inputs for subsequent read-only builds.
Season models share simulated remaining rounds for championship, qualifying,
fastest-lap and supported title-deciding questions. Predicates needing additional
verified historical facts stay unsupported when those facts are unavailable.

## Calibration and chronological evaluation

See the [2026 question coverage audit](predict-coverage.md) for supported counts,
unsupported historical questions and archived feed validation failures.

By default recommendations privately archive the **public point-in-time inputs
and raw forecasts**, without login cookies, GUIDs or saved account answers, under
`<account-dir>/predict/research/`. `--no-archive` disables this. After official results:

```sh
f1fantasy predict settle
f1fantasy predict backtest --format json
```

Settlement requires identical original questions/options/payouts, finalized
answers and unambiguous ordered podium positions. Backtesting uses the earliest
archived pre-lock forecast once per round, official payout/Boost scoring, Brier
and log losses and uniform baselines, both per question and per semantic model
type. It does not reconstruct pretend pre-lock prices/options from historical
result-bearing feeds.

Calibration fits a conservative raw/uniform mixture on at least **20 earlier
settled outcomes of the same semantic model type**. Settlement must precede the
forecast's observation time; repeated snapshots of one question do not manufacture
extra observations. Until then probabilities are explicitly **uncalibrated**.
There is no claimed historical accuracy improvement or guaranteed points without
that evidence. The daemon attempts archive settlement before each poll.

## Connect and submit

```sh
python -m pip install -e '.[account]'
f1fantasy predict account connect --timeout 600
f1fantasy predict account show --format json
f1fantasy predict account apply --format json
f1fantasy predict account audit --format json
```

Manual official login/MFA uses a dedicated persistent Predict Chromium profile.
There is no Fantasy team number: the observed Predict GUID is bound separately
under `<account-dir>/predict/`. Directories are private, state files checksummed
where appropriate, operations locked and journal writes atomic/fsynced. Browser
passwords and raw authentication responses are not logged. Expired sessions require
manual reconnection; profile creation/terms are never accepted automatically.

The shipped client saves one question per request. The implementation therefore
journals ordered steps, clears the old question Boost before moving it, and reads
back **all ten answers and their Boost allocation** after every save. This checks
unaffected questions and ordered podium entries as well as the changed question.
Prepared or uncertain requests are never blindly resent. Rerunning apply reconciles
the original journal first and resumes only provably unsent steps after fresh
account/question/window validation. Separate requests can leave a partial result;
there is no claim of an atomic ten-question server transaction.

### Current live verification limits

The current regular-round question feed and complete ten-question read-only
recommendation have been exercised live. Account payloads/readback and scheduler
behavior have offline contract tests based on the shipped official client;
**authenticated Predict login and successful answer submission are not live-verified**.

The observed public site exposes a countdown but no verified exact, event-bound
server lock timestamp. Its client adds 40 seconds to a session-based countdown;
that is not authority to write until that instant. Mutations and timed jobs
require the account adapter to observe an exact event-bound official deadline.
With the currently observed markup they report **blocked**. A user-entered timestamp,
session start or the Fantasy lock cannot bypass this requirement.

The current bonus feed also contradicts itself: the app's 2026 configuration is
paired with bonus schedule metadata for 2025. Season-bonus commands reject that
contradiction; coherent season fixtures are covered by model tests, not represented
as a verified live bonus recommendation.

## Optional CLI automation

Container deployment has been removed in favor of the static Fantasy website.
Predict remains a separate Python CLI. After `predict account connect`, run
`f1fantasy predict daemon run` on an awake, online machine to use its existing
independent scheduler. Its private Predict browser, binding and journals do not
select or change a Fantasy team. The static website does not expose this account
session or run Predict submissions.

The default Predict policy evaluates the newly published round 24 hours and 15
minutes before its **verified** deadline, with a 90-second safety cutoff, and
advances as official round identity changes. It refreshes questions, payouts,
account state and forecasts before each due operation. Bonus scheduling is separate
and explicit with `predict daemon run --scope season`. CLI controls are:

```sh
f1fantasy predict daemon run --once --format json
f1fantasy predict daemon status --format json
f1fantasy predict daemon retry JOB_ID
f1fantasy predict daemon cancel JOB_ID
```

`--once` is a real potentially submitting cycle. Failed jobs block later work until
explicit retry/cancel; uncertain jobs reconcile the matching saved account target
before any new recommendation. Restart/deadline changes cannot authorize unrelated
pending manual writes. Events are persisted and logged; `--notify-command /path/to/program`
receives sanitized JSON on stdin without a shell. Notification failure does not
turn a verified save into a submission failure. Use Ctrl+C to stop the process;
its private login, archives and job/account journals remain on disk.

## Official source contracts

- [Rules](https://f1predict.formula1.com/en/game-rules) and [FAQs](https://f1predict.formula1.com/en/faqs).
- Predict public feeds: `apps/web_config.json`, `limits/constraints.json`,
  `schedule/raceday_en.json`, `questions/questions_{gameday}_en.json`,
  `drivers/drivers_{gameday}_en.json` under the official `/feeds/` origin.
- Observed shipped bundles: `main.5c23e71f3c06b1f23612.js`,
  `components.924b264073a64dcf57dc.js`, `481.787f96c6ebc8e772cc71.chunk.js`.
- Cookie-backed read: `GET /services/user/gameplay/{guid}/{gameday}/prediction`;
  save: `POST /services/user/gameplay/prediction`, one `Predictions` item with
  `QuestionId`, ordered `SelectedOption` and `BoosterId`, plus `RaceId`,
  `GameDayId` and `PlatformId`. HTTP success alone is not verified application.
