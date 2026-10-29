# Optional CLI scheduling

The primary interface is now the [static season-planning website](website.md).
It does not run account jobs or submit team changes. Container deployment has
been removed; existing Python scheduling remains available for an explicitly
connected account on an awake, online machine.

```sh
source .venv/bin/activate
f1fantasy account connect --team 2
f1fantasy daemon run --season-plan --allow-penalties
```

This is an **unattended, potentially submitting** command. It refreshes the
selected account, prices, forecast and chips; jointly plans all remaining rounds;
and applies only the current round before reading back the live result. Without
`--season-plan`, `--races` retains its rolling-horizon meaning. Paid transfers are
opt-in and their −10-point cost is included in the objective.

Defaults are an early run 24 hours before the verified lock, a final run 15
minutes before lock, a 90-second no-write cutoff and a 60-second poll. Eligible
Final Fix is a separate official-window job using only remaining-session points.
The current site has exposed lock flags and a countdown but no verified exact
timestamp: pre-lock jobs report **blocked**, never reconstruct a deadline from
session starts or add a guessed grace period.

```sh
f1fantasy daemon run --once --format json
f1fantasy daemon status --format json
f1fantasy daemon audit --format json
f1fantasy daemon retry JOB_ID
f1fantasy daemon cancel JOB_ID
```

`--once` is a real possibly submitting cycle. Jobs and account journals persist
in the private account directory. Failed or uncertain jobs block subsequent
work until verified reconciliation or explicit retry/cancel; sent requests are
not blindly replayed. Running jobs retain original policy, team/event identity,
deadline and cutoff across restart. Cancelling a scheduler job never erases an
unresolved account write. Offline controls remain available between polls, while
a separate runner lock prevents duplicate daemons.

Notifications are sanitized JSON events. `--notify-command /path/to/executable`
passes an event on stdin without a shell. Delivery failure is recorded separately
from submission success. Headless authentication expiry blocks jobs and requires
interactive `account connect` again. See [account contracts and recovery](account-integration.md).
