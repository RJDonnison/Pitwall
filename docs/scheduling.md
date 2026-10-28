# Automatic scheduling with Docker

Due jobs submit and verify changes for the explicitly connected team throughout
the remaining season. Docker enables chip planning and paid transfers by default;
the optimizer deducts every transfer penalty from expected points. Interactive
CLI recommendations retain their three-round default and paid-transfer opt-in.
V4 Predict is not included.

## Start

Choose your official one-based team number, from the repository:

```sh
F1FANTASY_TEAM=2 docker compose up -d --build
docker compose logs -f fantasy
```

On first start, open
<http://localhost:6080/vnc.html?autoconnect=1&resize=scale>. Sign in to F1 in that
browser, complete MFA and open My Team. The container binds Team 2, closes the
interactive browser, and starts scheduling. Replace `2` with your team. A new
installation never guesses the team; an environment change cannot retarget a
saved binding. After initial login, use `docker compose up -d` for normal starts.

The container has its own persistent Chromium session; it does not copy or share
the host Arch browser profile. Chromium is installed inside the Debian image, so
no host Python/browser installation is needed. The image runs non-root with an
owned virtual display and a login UI published only to host loopback. On a remote
Docker host, use an SSH tunnel to its localhost port 6080.

Compose restarts after host reboot unless explicitly stopped. The named
`fantasy-data` volume preserves the session, binding, account journal, scheduler
audit/jobs and FastF1 cache. `docker compose down` keeps it; `down -v` erases it.
The image build context contains only package source and the manifest, never
local profiles, credentials, Git data or caches.

## Default policy

| Stage | When | Action |
| --- | --- | --- |
| Early | 24 hours before verified Fantasy lock | Refresh account/prices, optimize all remaining season rounds, apply this round and verify |
| Final | 15 minutes before verified Fantasy lock | Refresh everything and apply the final pre-lock plan |
| Safety cutoff | 90 seconds before lock | No new scheduled write may start |
| Final Fix | First eligible poll in the official post-qualifying window | Forecast only remaining sessions and apply an improving replacement |

Polling is every 60 seconds. Jobs persist account/team/season/event/phase and
lock/window identity. Restarts do not repeat completed stages. A restart near
lock skips the expired early stage. Official deadline changes supersede waiting
jobs; an interrupted job outside its saved window requires reconciliation.
Fresh lock, cap, net-transfer, roster/chip and read-back validation is shared
with manual apply.

### Season-long strategy

The image starts `daemon run --season-plan --allow-penalties`. Each pre-lock run
forecasts every remaining round of the connected season, rather than a rolling
three-round window. The optimizer jointly maximizes their summed expected points,
accounting for net transfers, −10-point paid transfers, carry, budget, Boost,
Sprint/regular format, chip eligibility, one chip per race and once-per-season
inventory. Default beyond-horizon chip reserves are zero because the horizon ends
at the season's final round; explicit reserve overrides remain user preferences.
Final Fix is still a separate future-session-only decision in its server window.

Only the first lineup is submitted. Future selections are provisional intentions,
not queued writes: fresh data triggers a new complete remaining-season plan on
the next stage/round. The scheduler follows the official current event and keeps
the same explicit team/season binding across restarts. Actual used-chip inventory
and transfer state come from each fresh account read, not an old forecast.
Completed pre-lock jobs retain `season_plan` with projected total points and the
round-by-round chip/transfer plan. Status exposes `planning_scope` even if a
deadline or session currently blocks scheduling.

This optimizes model expectations; it cannot guarantee actual season results.
Future prices are assumed constant until refreshed, and future results are never
used as predictions. Unknown externally-activated Limitless restoration blocks a
multi-round season plan rather than silently shortening it to one race. Uncertain
writes, authentication failures and unverified deadlines still require attention.
It does not silently rebind to a new season when the configured season ends.

**Current deadline gate:** the observed live website supplies lock flags and a
countdown but no verified timezone-bearing lock timestamp. In that state the
service runs and reports `blocked`; it cannot time the early/final jobs. It does
not substitute a qualifying/session start for the Fantasy lock deadline. Those
jobs submit only once a real verified deadline is available. Final Fix uses its
independent authoritative server window and does not require a pre-lock
timestamp. Check status: a running container is not proof that a timed job is
armed or completed. There is deliberately no guessed-deadline override.

## Status and notifications

```sh
docker compose ps
docker compose logs -f fantasy
docker compose exec fantasy f1fantasy daemon status --format json
docker compose exec fantasy f1fantasy daemon audit --format json
docker compose exec fantasy f1fantasy account audit --format json
```

Health is healthy only for a recent, unblocked scheduler heartbeat. Login in
progress, blocked state, or heartbeat older than 15 minutes is not healthy.
Docker does not restart just because health is unhealthy; inspect the reason in
status/logs. First login gets a 15-minute startup grace period.

Transitions emit sanitized JSON notifications in logs. Identical blocked polls
update the heartbeat without duplicate notification spam. Optional
`--notify-command /path/to/executable` receives each event as JSON stdin, without
a shell; mount that executable if needed. Delivery failure/timeout is recorded
separately and cannot reclassify a verified save. Account GUIDs, passwords,
cookies and raw responses are omitted.

## Renew login and recover jobs

An expired session blocks scheduling. Recreate to open the interactive browser:

```sh
F1FANTASY_TEAM=2 F1FANTASY_RECONNECT=1 docker compose up -d --force-recreate
```

After signing in through the same UI, clear forced renewal for future restarts:

```sh
F1FANTASY_TEAM=2 docker compose up -d --force-recreate
```

Failed/uncertain jobs block automatic continuation. Inspect both audits, then:

```sh
docker compose exec fantasy f1fantasy daemon retry JOB_ID
docker compose exec fantasy f1fantasy daemon cancel JOB_ID
```

Retry reconciles the saved plan on the next poll; it never blindly resends a
sent-but-uncertain operation. Never-sent combined steps resume only in their
original verified scheduled window. Pending manual plans cannot silently be
continued by the daemon. Cancel does not erase the account journal or make an
ambiguous write replayable. A combined apply may save a lineup before chip
activation stops; the audit identifies each step. Past-window uncertainty can
require manual reconciliation rather than a retry.

## Customize

Create a local ignored `compose.override.yaml`, then `docker compose up -d`:

```yaml
services:
  fantasy:
    command: [daemon, run, --season-plan, --allow-penalties, --early-hours, "24", --final-minutes, "20", --safety-seconds, "120", --poll-seconds, "60"]
```

Other flags include `--no-chips`, `--no-final-fix-enabled`, `--allow-penalties`,
`--no-telemetry`, `--no-risk`, and `--chip-reserve NAME=POINTS`. Timing requires
early > final > safety cutoff. Waiting jobs adopt the new policy; interrupted
jobs retain their saved policy. `daemon run --once` is a real potentially
submitting cycle, not a dry run.

To deliberately use a short rolling horizon in Docker, replace the command with
`[daemon, run, --no-season-plan, --races, "3"]`; omitting `--allow-penalties` also
returns to free transfers only. A custom Compose command replaces the image's
default flags. Ordinary host commands such as `f1fantasy recommend --races 3`
are unchanged. Pending jobs retain their original policy when the image is
upgraded; never-sent waiting jobs adopt the new season strategy on the next poll.

`F1FANTASY_LOGIN_PORT` changes the loopback UI port. `F1FANTASY_LOGIN_TIMEOUT`
defaults to 900 seconds. Build arguments `F1FANTASY_UID`/`F1FANTASY_GID` default
to 1000 for volume ownership; keep them stable after populating the volume.
Only one container should own an account directory. Locks reject overlapping
profile/scheduler operations. Without Docker, install `.[account]`, connect the
team, and run `f1fantasy daemon run` with system Chromium in headless mode.
