# Predict question coverage: 2026

This audit reviewed the official question contracts for all 19 completed regular
rounds and the published round 20: **200 questions**. It exercised the existing
forecast and answer-selection paths for each round whose feed passed validation,
using 4,000 simulations, seed 2026, telemetry disabled, and the committed historical
racing inputs available before that round. Fastest-pitstop questions also used the
existing earlier-label model.

Of the 160 questions in validated rounds, **114 were supported and 46 unsupported**.
The remaining **40 questions** belonged to four rounds blocked by contract or
roster validation. All ten questions in the current round 20 were supported.

This is a coverage review, not a historical accuracy backtest. Historical feeds
were fetched after their results were published; only their question contracts
were used, and public answer, finishing-position and chance fields were excluded
from model features. Point-in-time forecast archives are still required for the
[chronological evaluation](predict.md#calibration-and-chronological-evaluation).
The season bonus and earlier seasons were outside this audit.

## Unsupported questions by round

Question descriptions below are shortened for readability. A supported count
includes questions with a usable forecast and payout-aware answer selection.

| Round | Supported | Unsupported questions |
| --- | --- | --- |
| 1 | 6/10 | Number of teams reaching Q3; fastest pitstop without earlier verified winner labels; team with highest race finishing position; Safety Car/VSC in the first five laps. |
| 2 | 8/10 | Safety Car/VSC in the first ten laps; team scoring the most weekend points. |
| 3 | 7/10 | Number of teams reaching Q3; Safety Car/VSC in the first ten laps; team scoring the most weekend points. |
| 4 | 7/10 | Both Williams cars getting out of Q1; Safety Car/VSC in the first ten laps; Drivers' Championship leader after Miami. |
| 5 | 6/10 | Number of teams scoring Sprint points; both Racing Bulls cars getting out of Q1; number of Safety Car/VSC deployments; Teams' Championship comparison after Canada. |
| 6 | 7/10 | Aston Martin getting a car into Q2; number of red flags; all 22 cars completing the first lap. |
| 7 | 8/10 | Audi getting a car into Q3; any Safety Car/VSC during the race. |
| 8 | 8/10 | Haas getting a car into Q3; Safety Car/VSC in the first ten laps. |
| 9 | 5/10 | Number of teams scoring Sprint points; both Williams cars getting out of Q1; Safety Car/VSC in the first ten laps; number of British drivers scoring points; a British driver winning. |
| 10 | 6/10 | Both Racing Bulls cars reaching Q3; team scoring the most points; maximum positions gained by a driver; a new Belgian Grand Prix winner. |
| 11 | 6/10 | Both Aston Martin cars reaching Q2; any Safety Car/VSC during the race; team scoring the most points; a new Hungarian Grand Prix winner. |
| 15 | 7/10 | Number of teams reaching Q3; Safety Car/VSC in the first 15 laps; team scoring the most points. |
| 16 | 7/10 | Number of teams reaching Q3; Safety Car/VSC in the first 15 laps; team scoring the most points. |
| 17 | 7/10 | Both Aston Martin cars progressing beyond Q1; any Safety Car/VSC during the race; team scoring the most points. |
| 18 | 9/10 | A new Drivers' Champion being crowned that weekend. |
| 20 | 10/10 | None. |

Except for the first-round pitstop evidence gap, these questions currently return
an unrecognized or ambiguous predicate/options result. Some are variants of
already modeled concepts, but their particular wording or option contract is not
supported by the current adapter. Others need additional verified evidence, such
as Safety Car history, nationality or previous Grand Prix winners. Their answers
must not be inferred from a supported count for a different question.

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
unsupported questions above. Feed contents can change; recommendations always
validate freshly fetched contracts.
