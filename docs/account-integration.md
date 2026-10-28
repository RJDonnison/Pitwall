# One-team browser account integration

This module uses private contracts in the official shipped Fantasy web client.
Authenticated Team 2 reads, persistent session restoration and unchanged-lineup
apply have been verified. The official edit flow's ordinary save request was
captured with every non-read service request aborted; no team/chip was submitted.
The connected Team 2 subsequently completed a combined transfer and x3 activation;
fresh authenticated read-back matched every journaled postcondition. The service
returned `isextradrstaken: 6` (its chip ID), not boolean `1`. Chip usage fields
accept boolean-style values or their own known chip ID, and used chips must carry
a positive activation game day. Other chip identities are rejected. Other chip
activation/accounting branches remain live-unverified.
Unexpected schemas and missing evidence are errors, not fabricated defaults.

## API for the CLI owner

Install the optional extra (`pip install '.[account]'`) and Chromium. The launcher
prefers `PLAYWRIGHT_CHROMIUM_PATH`, then `chromium` or `chromium-browser` on PATH,
then Playwright's bundled browser. Arch Linux's `/usr/bin/chromium` is detected
automatically; no Playwright browser download is needed when using it.
Python Playwright documentation:

- <https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context>
- <https://playwright.dev/python/docs/api/class-apirequestcontext>

The functions in `f1fantasy.account` are synchronous:

```python
connect(directory: Path, season: int, team_number: int,
        timeout_seconds: int = 300) -> dict
show(directory: Path, season: int) -> dict
apply(directory: Path, season: int, proposal: dict,
      allow_penalties: bool = False) -> dict
audit(directory: Path) -> list[dict]
recover(directory: Path, season: int, *, confirm_completed: bool = True) -> dict | None
final_fix_context(directory: Path, season: int) -> dict
apply_final_fix(directory: Path, season: int, proposal: dict) -> dict
```

Failures raise `AccountError`, a subclass of `DataError`. The CLI should catch
that type, present the message, and not retry writes automatically. Browser
exception strings, response bodies, URLs containing account identity, cookies,
passwords, tokens and account names are never included in the module's errors
or journal. `connect` opens a headed browser; the user follows the official
Sign In and MFA flow manually. No password is collected by Python. Completion
requires an actual successful official `getteam` browser response containing
the account GUID in its URL, followed by fresh selected-team reconciliation.
A login cookie, public picker, or persisted local draft is insufficient.

Each configured directory owns **one account/season/team binding**. Use a
dedicated directory outside the repository; do not use a normal Chrome user
profile. Directory and browser-profile directory permissions are 0700. Binding,
journal and lock files use 0600. Operations use a nonblocking Linux `flock` and
hold it throughout browser use. Overlapping operations fail. A nonempty journal
prevents rebinding the same directory to another identity; choose a new directory
instead. Browser data is managed by Chromium under the private parent directory.
Session restoration has been verified. MFA/expired sessions return through the
official interactive login rather than accepting a stale login cookie.

## Normalized `show` result

The selected team only is returned, without GUID, team name or cookies:

- `season`, `team_number`, `gameday_id`, `phase_id`
- `drivers`: five string IDs; `constructors`: two string IDs
- `boost_driver_id`, `x3_driver_id` (nullable)
- `budget`: total account cost cap **in millions**, suitable for CLI
  `_validate_state`; this is not the unspent bank balance
- `budget_tenths_m`, `remaining_budget_tenths_m`
- `carry`: zero or one; `baseline_ids`: original `gd_initial_team`
- `available_chips`, `eligible_chips`, `active_chip`
- `lock_deadline_utc` (nullable), `locked`, `fetched_at`
- `unlimited_transfers`, `net_transfers`, `transfer_allowance`,
  `transfers_left`, `transfer_penalty`
- `limitless_restoration_ids` when a verified local activation journal identifies
  the actual seven selected immediately before Limitless activation
- In the Final Fix window or after activation: `final_fix_window`, retained
  session evidence, `retained_points`, `accrued_points`, and the verified
  `final_fix` replacement identity when present

Chip names are `limitless`, `wildcard`, `final_fix`, `autopilot`, `no_negative`,
and `x3`. Availability means unused; eligibility is more restrictive. The parser
requires the observed per-chip history fields and selected-team `mddetails`.
Unknown statuses, inconsistent balance/current prices, ambiguous combined swap
histories, and missing history fail closed. A verified Final Fix eight-entry
history is reconciled to seven effective selections plus the retained outgoing
entry and original Boost. Seven current
IDs are joined to the fresh active roster. An inactive current selection cannot
currently be reconciled and is an explicit error.

Both show and apply fetch current public schedule, active prices and statistics;
the latter cross-checks prices with the roster using existing data-layer
validation. A second fresh roster verifies `Skill` and price stability for the
wire payload. No previous-week-price fallback or forecast result is cached here.
The event must match the freshly observed official read URL and current fixture.

## Proposal contract and forecast ownership

`apply` requires all these keys:

```json
{
  "season": 2026,
  "gameday_id": 19,
  "drivers": ["1", "2", "3", "4", "5"],
  "constructors": ["11", "12"],
  "boost_driver_id": "1",
  "chip": null,
  "x3_driver_id": null,
  "budget_tenths_m": 1000,
  "baseline_ids": ["1", "2", "3", "4", "5", "11", "12"],
  "expected_transfer_penalty": 0
}
```

IDs above are illustrative offline fixtures, not a real recommended team.
`budget_tenths_m` is the account's total cost cap; it is compared with the fresh
remote cap, never accepted as a price source. Net transfers compare the proposed
seven selections against the remote original baseline, not the latest local
edit. Paid transfers require both the expected penalty and explicit permission.

**The main CLI owns forecast recomputation.** Call show, fetch the live planning
snapshot, recompute forecasts/recommendation, then call apply with that proposal.
If apply reports an event/baseline/budget/price/penalty conflict, return to that
step rather than resubmitting the old recommendation. This module has no model
callback and makes no claim to validate forecast quality. Apply refreshes account,
prices/statistics and roster itself before any mutation.

## Fresh server lock checks

Apply re-fetches the official schedule immediately before preparing a write.
It requires exactly one current, non-postponed fixture matching the bound season,
Fantasy game day and phase, and verified false `GDIsLocked`, `MDIsLocked` and
`MHIsLocked` flags. Missing/unknown flags, changed event/session or a locked flag
stop the write before journal preparation. A nonzero authenticated team session
status also blocks ordinary changes. The server remains authoritative if the
lock changes between preflight and receipt; only matching read-back proves success.

An explicit timezone-bearing remote timestamp, when present, is additionally
checked before and after journal preparation. The optional markup probe accepts
a unique `time[datetime]` inside `section[aria-label="team lock deadline"]`.
This markup has not been observed: the current authenticated page exposes only
days/hours/minutes countdown labels, so `lock_deadline_utc` may remain null.
No session-start fallback, countdown reconstruction or hardcoded buffer is used.

The shipped countdown adds 40 seconds to session start. This is not proof of the
server lock boundary. `NextMatchDeadline: "0"` is not an authoritative timestamp.
Fresh event/session lock flags are used directly rather than inventing a timestamp.

## Final Fix window and retained scoring

`final_fix_context` requires the official `IsFinalFixActive` flag and verified
session statuses, category and race-day identity. The selected team must be
post-qualifying, unused for Final Fix, not late, and have no other active chip.
An upcoming qualifying session, in-progress session, locked remaining session,
unknown status or closed window prevents submission. No scheduled-time fallback
is used. Regular Race and the feed's `Sprint Qualifying` (Sprint scoring) sessions
are distinguished explicitly.

The context returns `state`, original `weekend`, fresh `assets`,
`remaining_sessions`, official multiplier-adjusted `accrued_points`, `eligible`
and `window`. Every retained session must be finalized and have finite official
per-selection scoring. The CLI forecasts remaining sessions only, with the
original pre-weekend historical cutoff. It does not feed elapsed results back
into those forecasts.

A Final Fix proposal extends the normal proposal with `outgoing_id`,
`incoming_id`, current pre-replacement `original_ids`,
`original_boost_driver_id`, `window` and `retained_points`. Apply requires one
same-kind affordable replacement, the inherited Boost and unchanged transfer
penalty. The server window is checked again after durable preparation. Read-back
verifies eight scoring entries, seven effective selections, original selections,
retained points and the replacement's exact race-day/category boundary. Ambiguous
outcomes retain the ordinary journal's no-replay rule. This path is implemented
and fixture-tested; the window was closed during development, so successful live
Final Fix submission remains unverified.

## Single-request writes

Observed service origin: `https://fantasy.formula1.com`.

| Action | Path |
| --- | --- |
| Read team | `GET /services/user/gameplay/{guid}/getteam/1/{teamNo}/{gameday}/{phase}` |
| Read history | `GET /services/user/gameplay/{guid}/getusergamedaysv1/1` |
| Ordinary/Wildcard lineup | `POST /services/user/gameplay/transferteam` |
| Boost only | `POST /services/user/gameplay/captainupdate` |
| Initial Limitless activation | `POST /services/user/booster/applylimitless` |
| Active Limitless/AP/No Negative/x3 roster edit | `POST /services/user/gameplay/transferteam` |
| Final Fix replacement | `POST /services/user/booster/applyfinalfix` |
| Standalone Autopilot | `POST /services/user/booster/applydrsenabled` |
| Standalone No Negative | `POST /services/user/booster/applynonegative` |
| Standalone x3 | `POST /services/user/booster/applymegadriver` |
| Active x3 allocation | `POST /services/user/booster/megadriverchange` |

Context requests share the persistent browser cookies. Every write has redirects
and transport retries disabled. There is no credential replay/session-login
endpoint implementation. Ordinary and Wildcard payloads contain all seven IDs,
positions and fresh roster skills. Limitless uses the observed distinct `position`
and `skill` keys. Standalone x3 can carry its two explicit multiplier selections.
Combined lineup/Boost changes and new Autopilot/No Negative/x3 activation use a
durable two-step plan. Both operations are validated before any mutation. First
the ordinary lineup/Boost is saved and fully read back; only then is the chip
activated and read back. x3 may name an incoming driver after that driver has
been verified in the saved lineup. A Boost-only change plus x3 remains one chip
request, since that endpoint supports both multiplier allocations directly.
Active chips cannot be cancelled or replaced. Already-active Limitless uses
`transferteam` with `boosterId: 1`; Boost-only edits use `captainupdate`. The
activation endpoint is not called again. The journal records the actual draft at
activation for later restoration, distinct from the original transfer baseline.
If activation occurred externally and restoration is unknown, the CLI limits
planning to the current weekend. No server transaction/idempotency guarantee has been
established; partial completion is possible and is explicitly reported.

Authenticated UI inspection confirmed that selecting No Negative in a transfer
draft issues `applynonegative` separately, before the eventual `transferteam`
request. Both requests were aborted during inspection. A `boosterId` on the later
transfer payload therefore does not prove it can atomically activate the chip.
Our staged implementation saves the lineup first to avoid consuming a chip
before the lineup has been verified. This order uses the separately observed
endpoints. The combined transfer/x3 sequence has since been verified against the
connected Team 2's saved roster, multipliers, chip history and transfer accounting.

Read-back conservatively requires the same verified cost cap and balance equal
to cap minus current roster cost (a signed balance is accepted only for active
Limitless). For unlimited chips it requires transfer counters to remain unchanged.
Those accounting postconditions are **not live-verified server behavior**. A
different server accounting convention produces an unknown outcome and blocks
further writes, rather than pretending the chip save was verified.

## Journal, restart recovery and audit

`binding.json` contains the minimal private GUID/season/team binding.
`journal.json` is both the sanitized audit and durable idempotency journal. Each
entry records proposal/binding hash, an integrity checksum, operation name, timestamps, status and the
expected normalized read-back. Account GUIDs, raw payloads and responses are not
stored in the journal. Writes use a private temporary file, fsync, atomic replace
and directory fsync. A prepare entry is durable **before** the mutation. Combined
entries additionally retain the normalized target proposals, original penalty
permission, per-step preconditions/expected states and ready/prepared/unknown/
verified progress. The public audit includes progress but omits stored proposals.

Proposal ID ordering is canonicalized for idempotency. A repeat or unresolved
prepare first obtains fresh account state. If every expected postcondition
matches, it marks verified without another POST, including after a lock deadline
has passed. If the outcome differs, it fails without replay, even if the old
lineup is still visible. A different proposal is also blocked while an unresolved
entry conflicts with live state. Never delete a journal entry to force a retry;
investigate the account state manually.

Read-back checks all seven IDs, both multiplier allocations, active chip and
remaining chips, original baseline, event/phase/team, budget/balance, net
transfers, allowance, remaining transfers and penalty. HTTP success or a success
toast alone is insufficient. A timeout/rejected response still triggers read-back
because the write may have committed. A read failure/mismatch retains `unknown`;
a process interruption leaves `prepared`, with the same no-replay semantics.
`audit()` does not launch the browser. The [Docker scheduler](scheduling.md)
uses this same apply/recovery path with persisted account/team/event identity,
verified deadline and safety-cutoff guards. Those guards are rechecked after
durable preparation and before each new combined step. A pending manual plan
cannot be silently continued as an unrelated scheduled action. Recovery may
verify sent operations after a deadline, but cannot start a new write outside
the saved scheduling window.

The CLI calls `recover()` before forecasting a new apply. Single-operation
recovery checks expected postconditions and never posts again. Combined recovery
first reconciles any prepared/unknown step against fresh read-back without
reposting it, then may send a subsequent **ready (never sent)** step from the
original durable plan. It revalidates current prices/accounting, event/phase,
chip eligibility, transfer permission and locks before that step. External edits
or ambiguous read-back block continuation. A lock between steps leaves the
verified lineup saved and chip step ready; rerunning apply can resume it only
while the same event/session remains eligible and unlocked. There is no automatic
rollback or chip cancellation. Errors identify completed operations, and audit
exposes each step's status. Recovery also works after chip activation makes
ordinary new planning ineligible; changing flags does not replace a pending plan.

A matching completed chip apply is freshly confirmed by default. Explicit
`account apply --replan` skips only that completed confirmation and optimizes a
new target while preserving the active chip; pending recovery still runs first.
`--final-fix` similarly requests a distinct remaining-session evaluation rather
than returning a confirmation of an unrelated completed chip apply.

## Research provenance and verification gaps

Official pages: <https://fantasy.formula1.com/en/create-team>,
<https://fantasy.formula1.com/en/faqs>,
<https://fantasy.formula1.com/en/game-rules>.
Public shipped sources captured October 26, 2026:

- `/static-assets/build/static/js/main.e05649f5.js`: modules 1423 (auth
  predicate), 1973 (constants), 7361 (HTTP), 8006 (services), 6983 (countdown);
  transfer calculation around character 87542; team normalizer around 1061983.
- `/static-assets/build/static/js/50.d56aac48.chunk.js`: mutation callers
  around characters 78000–82280.
- `/static-assets/build/static/js/431.6be943a9.chunk.js`: standalone chip
  payloads around characters 8500–9100.
- `/feeds/v2/schedule/raceday_en.json`, `/feeds/drivers/19_en.json`,
  `/feeds/live/mixapi.json`.

The read parser requires `Meta.Success === true`, `Data.Value.userTeam`, raw
`playerpostion`, the observed chip fields, and the observed history structure.
These shapes originate in shipped consumers and have been checked against
authenticated Team 2 reads, persistent session restoration, transfer/x3 saves and
durable recovery. Closed Final Fix windows and conflicting active chips were
observed without mutation. Successful Final Fix submission and non-x3 chip
accounting still require live-window verification; their offline fixtures do not
claim otherwise. Active Limitless routing was established in chunk 50's save
branch: `applyLimitless` is selected only when `boosterid !== 1`, with subsequent
edits falling through to `transferTeam`. Unknown responses must extend the
evidence/tests before extending accepted schemas.
