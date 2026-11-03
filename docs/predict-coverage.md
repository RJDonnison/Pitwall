# Predict question coverage: 2026

This audit reviewed the official question contracts for all 19 completed regular
rounds and the published round 20: **200 questions**. After adding the missing
question families, it exercised the forecast and answer-selection paths for each
round whose feed passed validation,
using 4,000 simulations, seed 2026, telemetry disabled, and the committed historical
racing inputs available before that round. Fastest-pitstop questions used earlier
official winner labels or the measured stationary-stop model when no such label
was available.

All **160 questions in validated rounds are now supported**, including the
**46 previously unsupported questions**.
The remaining **40 questions** belonged to four rounds blocked by contract or
roster validation. All ten questions in the current round 20 were supported.

This is a coverage review, not a historical accuracy backtest. Historical feeds
were fetched after their results were published; only their question contracts
were used, and public answer, finishing-position and chance fields were excluded
from model features. Point-in-time forecast archives are still required for the
[chronological evaluation](predict.md#calibration-and-chronological-evaluation).
The season bonus and earlier seasons were outside this audit.

## Previously unsupported questions: now covered

Question descriptions below are shortened for readability. A supported count
includes questions with a usable forecast and payout-aware answer selection.

| Round | Supported | Newly supported questions |
| --- | --- | --- |
| 1 | 10/10 | Number of teams reaching Q3; fastest pitstop using earlier measured stationary-stop events; team with highest race finishing position; Safety Car/VSC in the first five laps. |
| 2 | 10/10 | Safety Car/VSC in the first ten laps; team scoring the most weekend points. |
| 3 | 10/10 | Number of teams reaching Q3; Safety Car/VSC in the first ten laps; team scoring the most weekend points. |
| 4 | 10/10 | Both Williams cars getting out of Q1; Safety Car/VSC in the first ten laps; Drivers' Championship leader after Miami. |
| 5 | 10/10 | Number of teams scoring Sprint points; both Racing Bulls cars getting out of Q1; number of Safety Car/VSC deployments; Teams' Championship comparison after Canada. |
| 6 | 10/10 | Aston Martin getting a car into Q2; number of red flags; all 22 cars completing the first lap. |
| 7 | 10/10 | Audi getting a car into Q3; any Safety Car/VSC during the race. |
| 8 | 10/10 | Haas getting a car into Q3; Safety Car/VSC in the first ten laps. |
| 9 | 10/10 | Number of teams scoring Sprint points; both Williams cars getting out of Q1; Safety Car/VSC in the first ten laps; number of British drivers scoring points; a British driver winning. |
| 10 | 10/10 | Both Racing Bulls cars reaching Q3; team scoring the most points; maximum positions gained by a driver; a new Belgian Grand Prix winner. |
| 11 | 10/10 | Both Aston Martin cars reaching Q2; any Safety Car/VSC during the race; team scoring the most points; a new Hungarian Grand Prix winner. |
| 15 | 10/10 | Number of teams reaching Q3; Safety Car/VSC in the first 15 laps; team scoring the most points, including an explicit tied answer. |
| 16 | 10/10 | Number of teams reaching Q3; Safety Car/VSC in the first 15 laps; team scoring the most points. |
| 17 | 10/10 | Both Aston Martin cars progressing beyond Q1; any Safety Car/VSC during the race; team scoring the most points. |
| 18 | 10/10 | A new Drivers' Champion being crowned that weekend. |
| 20 | 10/10 | None. |

The replay uses the committed archive's 66 completed-race observation records,
1,171 sourced Grand Prix winner entries (including shared winners), sporting
nationalities and measured stationary-stop events, filtered at each round's
cutoff. Racing questions use the shared qualifying/Sprint/race draws. Empirical
intervention estimates and the preseason pitstop model remain explicitly
uncalibrated until sufficient point-in-time forecasts can be evaluated. Missing
required evidence still produces an unsupported result rather than an invented
answer.

## Archived feed validation failures

All ten question texts in each of these rounds were inspected, but the complete
round could not produce a verified recommendation:

| Round | Meeting | Blocking validation result |
| --- | --- | --- |
| 12 | Dutch Grand Prix | An option is absent from its own active roster. The feed also numbers its questions 11–20 rather than the required 1–10. |
| 13 | Italian Grand Prix | Unknown ordered podium contract. |
| 14 | Spanish/Madrid Grand Prix | The driver roster does not satisfy verified, unique driver identity requirements. |
| 19 | Mexico City Grand Prix | An option is absent from its own active roster. |

These are full-round validation failures, not evidence that every question type
in those rounds lacks a model. They are kept separate from the 46 individual
question-support gaps resolved above. Feed contents can change; recommendations
always validate freshly fetched contracts.
