# One-team unattended scheduling

`f1fantasy daemon run` watches the explicitly connected account team and submits
due jobs automatically. Chip decisions use the full multi-race model, refreshed
account state, verified live prices/statistics and remaining inventory. The
daemon uses the existing persistent Chromium profile in headless mode; interactive
`account connect --team N` remains the way to sign in or renew MFA.

## Commands

From the project directory, with the account already connected:

```sh
source .venv/bin/activate
f1fantasy daemon run --once
f1fantasy daemon status
f1fantasy daemon audit --format json
f1fantasy daemon run
```

`--once` runs one real polling cycle: it can submit a due job. It returns 1 when
blocked and 0 when the cycle succeeds or is waiting. Continuous operation keeps
watching when blocked and emits state changes as JSON notifications on stderr.
`--format json` returns the versioned state envelope; continuous mode writes one
JSON envelope per polling cycle (JSON Lines). Status and audit are offline.

Defaults:

| Setting | Default |
| --- | --- |
| Early run | 24 hours before verified Fantasy lock |
| Final run | 15 minutes before verified Fantasy lock |
| No-new-submission safety cutoff | 90 seconds before lock |
| Poll interval | 60 seconds |
| Horizon | 3 races |
| Chips and post-qualifying Final Fix | Enabled |
| Paid transfers | Disabled |

```sh
f1fantasy daemon run --early-hours 36 --final-minutes 20 --safety-seconds 120 --poll-seconds 60 --races 3
f1fantasy daemon run --no-chips --no-final-fix-enabled
```

`--no-chips` disables new pre-weekend chip spending, not effects already active.
Final Fix has a separate switch because it is evaluated in a different window.
The normal forecast, chip-reserve and explicit paid-transfer options are accepted.

## Deadline authority

Pre-lock jobs require a freshly observed, timezone-bearing **actual Fantasy lock
deadline**. Qualifying time, Sprint time, a rounded countdown and the shipped
countdown's 40-second adjustment are not substitutes. If the site exposes only
lock flags/countdown, status is `blocked` with a reason and **no scheduled
pre-lock write occurs**. Manual `account apply` can still use its fresh server
lock checks. There is deliberately no user-supplied deadline override that could
silently turn an inferred time into server authority.

The currently observed site exposes no verified lock timestamp, so this gate
currently blocks early/final auto-submission. This is an integration limitation,
not a successful live scheduling verification. The daemon is ready to schedule
when an authoritative timestamp is exposed by the supported account reader.

Final Fix is independent: it runs only when the server's verified Final Fix
window is open and the team is eligible. It uses official completed-session
scores and forecasts only remaining sessions. Session dates never authorize a
write by themselves. Another active chip makes Final Fix ineligible.

## Persistence, restart and changes

Private state is stored in `<account-dir>/scheduler/state.json` (directory 0700,
file 0600, atomic/fsynced writes). The account's original apply journal remains
the authority for whether a submitted operation committed. A separate scheduler
lock prevents overlapping daemons; account operations retain their profile lock.
The scheduler is bound to the connected account identity, season and selected
team, not whichever card the website happens to display.

Job identity includes team, event, phase, stage and verified deadline/window.
Each stage runs once per identity. A moved deadline supersedes waiting jobs and
creates new times. On a late restart, an expired early stage is skipped in favor
of the final stage; no new submission starts inside the safety cutoff. Timing and
policy changes affect waiting jobs, while interrupted operations retain their
saved policy and original account proposal.

An interrupted eligible job resumes through account recovery before forecasting.
Already-sent ambiguous steps are read back, never blindly resent. A changed
event/window or passed cutoff stops automatic recovery that could send another
step. Each submission checks the exact scheduled team/session/deadline again
after forecasting and immediately before sending, including each combined step.
The server's own lock checks and complete account read-back remain mandatory.

Failures block subsequent jobs. Inspect both journals before explicitly allowing
recovery:

```sh
f1fantasy daemon status --format json
f1fantasy account audit --format json
f1fantasy daemon retry JOB_ID
```

Retry is processed on the next cycle only while the original window/cutoff still
permits it. For a past job, reconcile with `account apply` as appropriate, then
use `daemon cancel JOB_ID` to retire the scheduler job. Cancel does not roll back
the team, refund a chip, or clear the account's uncertainty journal; that journal
will still prevent conflicting writes.

SIGINT/SIGTERM stop polling after the current operation finishes. A forced kill
may leave a running job, which is reconciled on restart. Keep the machine awake
and its clock synchronized; this daemon cannot run while the machine is off.

## Notifications

Every verified, missed, superseded, blocked or failed transition is persisted in
daemon audit and emitted on stderr (and therefore the service journal). Repeated
identical blocked polls do not spam transition notifications.

For external delivery, supply an executable that receives sanitized event JSON
on standard input:

```sh
f1fantasy daemon run --notify-command /absolute/path/to/notify-fantasy
```

The command is invoked directly without a shell, with a 15-second timeout. It
receives job IDs, stage/status and sanitized summaries, not cookies, GUIDs or raw
service bodies. Credentials belong in that executable's private environment or
secret store. Notification failures are recorded separately and never turn a
verified submission into a failed submission. Events remain in local audit even
if notification delivery is interrupted.

## Always-on Arch/Linux user service

Create `~/.config/systemd/user/f1fantasy.service`, changing the two project paths
for your installation:

```ini
[Unit]
Description=F1 Fantasy one-team scheduler

[Service]
Type=exec
WorkingDirectory=/home/reujdon/Repos/f1
ExecStart=/home/reujdon/Repos/f1/.venv/bin/f1fantasy daemon run
Environment=PYTHONUNBUFFERED=1
Environment=PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium
Restart=on-failure
RestartSec=60
KillMode=mixed
TimeoutStopSec=300
UMask=0077

[Install]
WantedBy=default.target
```

The daemon selects headless mode itself. Use the same Linux user and account
directory as interactive connect. The existing Arch Chromium installation is
used; no Playwright browser download is required. Use an absolute
`--account-dir /path` before `daemon` in `ExecStart` if you use a custom profile.

```sh
systemctl --user daemon-reload
systemctl --user enable --now f1fantasy.service
systemctl --user status f1fantasy.service
journalctl --user-unit=f1fantasy.service -f
```

To keep the user service manager running after logout, enable lingering for your
user with `loginctl enable-linger "$USER"` where permitted. Stop the service before
interactive reconnect if it is currently using the browser profile:

```sh
systemctl --user stop f1fantasy.service
f1fantasy account connect --team 2 --timeout 600
systemctl --user start f1fantasy.service
```

No service is installed or enabled automatically by the CLI. Scheduling does not
extend into F1 Predict.
