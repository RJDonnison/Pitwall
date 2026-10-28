"""Verified deadlines, durable jobs and account no-replay guards."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from f1fantasy import account, cli, scheduler
from f1fantasy.data import DataError
from test_account import (
    raw,
    fixture,
    history,
    catalog,
    state,
    proposal,
    install,
    after_state,
)

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
BINDING = account._binding_fingerprint(
    dict(guid="account-identity", season=2026, team_number=2)
)


@pytest.fixture
def setup(tmp_path):
    account._atomic(
        tmp_path / "binding.json", dict(guid="test-guid", season=2026, team_number=2)
    )
    live = dict(
        season=2026,
        team_number=2,
        gameday_id=19,
        phase_id=1,
        locked=False,
        eligible_chips=[],
        lock_deadline_utc=(NOW + timedelta(hours=12)).isoformat(),
    )
    policy = dict(
        early_hours=24,
        final_minutes=15,
        safety_seconds=90,
        poll_seconds=60,
        races=3,
        chips=True,
        chip=None,
        chip_reserve=[],
        allow_penalties=False,
        no_telemetry=True,
        no_risk=True,
        final_fix_enabled=True,
    )
    calls, events = [], []

    def execute(job):
        calls.append(deepcopy(job))
        return dict(apply_status="verified", idempotency_key="account-key")

    def tick(now=NOW, runner=execute):
        return scheduler.tick(
            tmp_path,
            2026,
            policy,
            lambda: deepcopy(live),
            runner,
            notify=events.append,
            now=now,
        )

    return tmp_path, live, policy, calls, events, tick


def test_stages_run_once_each_with_persistent_identity(setup):
    path, live, _, calls, events, tick = setup
    first = tick()
    assert [j["stage"] for j in calls] == ["early"]
    assert tick()["jobs"] == first["jobs"]
    deadline = scheduler.timestamp(live["lock_deadline_utc"])
    tick(deadline - timedelta(minutes=14))
    tick(deadline - timedelta(minutes=10))
    assert [j["stage"] for j in calls] == ["early", "final"]
    assert len(events) == 2
    assert (path / "scheduler/state.json").stat().st_mode & 0o777 == 0o600
    assert "test-guid" not in json.dumps(first)


def test_late_restart_and_cutoff_never_catch_up_old_writes(setup):
    _, live, _, calls, _, tick = setup
    deadline = scheduler.timestamp(live["lock_deadline_utc"])
    result = tick(deadline - timedelta(minutes=10))
    assert [j["stage"] for j in calls] == ["final"]
    assert any(j["status"] == "missed" for j in result["jobs"].values())
    live["gameday_id"] += 1
    tick(deadline - timedelta(seconds=30))
    assert len(calls) == 1
    live["locked"] = True
    tick(deadline)
    assert len(calls) == 1


@pytest.mark.parametrize("deadline", [None, "0", "2026-10-30T12:00:00"])
def test_missing_deadline_blocks_without_session_time_fallback(setup, deadline):
    path, live, _, calls, events, tick = setup
    live.update(
        lock_deadline_utc=deadline,
        first_session_utc=(NOW + timedelta(hours=12)).isoformat(),
    )
    assert tick()["status"] == "blocked"
    tick(NOW + timedelta(minutes=2))
    assert not calls and len(events) == 1
    assert (
        scheduler.status(path)["checked_at"] == (NOW + timedelta(minutes=2)).isoformat()
    )


def test_schedule_changes_supersede_waiting_jobs(setup):
    _, live, policy, calls, _, tick = setup
    first = tick()
    old_final = next(j["id"] for j in first["jobs"].values() if j["stage"] == "final")
    live["lock_deadline_utc"] = (NOW + timedelta(days=2)).isoformat()
    result = tick()
    assert result["jobs"][old_final]["status"] == "superseded"
    policy["early_hours"] = 60
    tick()
    assert len(calls) == 2


def test_final_fix_is_separate_from_prelock_timestamp(setup):
    _, live, _, calls, _, tick = setup
    live.update(
        locked=True,
        lock_deadline_utc=None,
        eligible_chips=["final_fix"],
        final_fix_window=dict(open=True, raceday=44, race_category="R"),
    )
    tick()
    tick()
    assert [j["stage"] for j in calls] == ["final_fix"]
    live["final_fix_window"]["open"] = False
    tick()
    assert len(calls) == 1


def test_failure_needs_explicit_retry_and_does_not_leak_service_errors(setup):
    path, _, _, calls, _, tick = setup

    def fail(job):
        raise DataError("private service error")

    result = tick(runner=fail)
    job = next(j for j in result["jobs"].values() if j["status"] == "failed")
    assert tick()["status"] == "blocked" and not calls
    assert "private service" not in json.dumps(result)
    scheduler.change_job(path, job["id"], "retry")
    tick()
    assert len(calls) == 1


def test_interrupted_job_retains_policy_and_cannot_move_windows(setup):
    path, live, policy, calls, _, tick = setup

    def crash(job):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tick(runner=crash)
    saved = next(
        j for j in scheduler.status(path)["jobs"].values() if j["status"] == "running"
    )
    policy["chips"] = False
    tick()
    assert calls[0]["id"] == saved["id"] and calls[0]["policy"]["chips"] is True
    live["gameday_id"] += 1
    with pytest.raises(KeyboardInterrupt):
        tick(runner=crash)
    live["gameday_id"] += 1
    assert tick()["status"] == "blocked"


def test_notification_failure_does_not_fail_verified_job(setup):
    path, live, policy, _, _, _ = setup

    def notify(event):
        raise RuntimeError

    result = scheduler.tick(
        path,
        2026,
        policy,
        lambda: live,
        lambda job: dict(apply_status="unchanged"),
        notify=notify,
        now=NOW,
    )
    assert any(j["status"] == "verified" for j in result["jobs"].values())
    assert result["events"][-1]["notification_error"]


def test_changed_binding_and_unknown_job_state_never_replay(setup):
    path, _, _, calls, _, tick = setup
    result = tick()
    key = next(iter(result["jobs"]))
    result["jobs"][key]["status"] = "future_status"
    account._atomic(path / "scheduler/state.json", result)
    with pytest.raises(DataError, match="no automatic replay"):
        tick()
    result["jobs"][key]["status"] = "verified"
    account._atomic(path / "scheduler/state.json", result)
    account._atomic(
        path / "binding.json", dict(guid="other", season=2026, team_number=2)
    )
    with pytest.raises(DataError, match="binding changed"):
        tick()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("early_hours", float("nan")),
        ("final_minutes", 1),
        ("poll_seconds", 0),
        ("races", 6),
    ],
)
def test_invalid_policy_is_rejected(setup, key, value):
    _, _, policy, calls, _, tick = setup
    policy[key] = value
    with pytest.raises(DataError):
        tick()
    assert not calls


def guard(state):
    return dict(
        team_number=2,
        phase_id=1,
        account_binding=BINDING,
        deadline=state["lock_deadline_utc"],
        cutoff=(NOW + timedelta(minutes=55)).isoformat(),
    )


@pytest.mark.parametrize(
    "change", ["deadline", "cutoff", "team_number", "phase_id", "account_binding"]
)
def test_scheduled_apply_guards_before_preparing(
    tmp_path, monkeypatch, state, catalog, proposal, change
):
    monkeypatch.setattr(account, "_now", lambda: NOW)
    state["lock_deadline_utc"] = (NOW + timedelta(hours=1)).isoformat()
    proposal["scheduled"] = guard(state)
    if change in {"team_number", "phase_id"}:
        proposal["scheduled"][change] += 1
    elif change == "account_binding":
        proposal["scheduled"][change] = "0" * 64
    else:
        proposal["scheduled"][change] = (
            NOW + timedelta(hours=2)
            if change == "deadline"
            else NOW - timedelta(seconds=1)
        ).isoformat()
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(DataError, match="Scheduled"):
        account.apply(tmp_path, 2026, proposal)
    assert not session.posts and not (tmp_path / "journal.json").exists()


def test_cutoff_after_prepare_and_between_combined_steps_prevents_post(
    tmp_path, monkeypatch, state, catalog, proposal
):
    clock = [NOW]
    monkeypatch.setattr(account, "_now", lambda: clock[0])
    state["lock_deadline_utc"] = (NOW + timedelta(hours=1)).isoformat()
    proposal["scheduled"] = guard(state)
    session = install(monkeypatch, tmp_path, [state], catalog)
    original = account._save_ledger

    def prepare(directory, rows):
        original(directory, rows)
        clock[0] = NOW + timedelta(minutes=56)

    monkeypatch.setattr(account, "_save_ledger", prepare)
    with pytest.raises(DataError, match="safety cutoff"):
        account.apply(tmp_path, 2026, proposal)
    assert not session.posts


def test_combined_activation_stops_if_cutoff_passes_after_lineup(
    tmp_path, monkeypatch, state, catalog, proposal
):
    clock = [NOW]
    monkeypatch.setattr(account, "_now", lambda: clock[0])
    state["lock_deadline_utc"] = (NOW + timedelta(hours=1)).isoformat()
    proposal.update(chip="x3", x3_driver_id="6")
    middle = after_state(state, catalog, dict(proposal, chip=None, x3_driver_id=None))
    proposal["scheduled"] = guard(state)
    session = install(monkeypatch, tmp_path, [state, middle], catalog)
    original = session.post

    def post(*args):
        original(*args)
        clock[0] = NOW + timedelta(minutes=56)

    session.post = post
    with pytest.raises(DataError, match="safety cutoff"):
        account.apply(tmp_path, 2026, proposal)
    assert len(session.posts) == 1


def test_unrelated_manual_pending_plan_cannot_be_continued_by_scheduler(
    tmp_path, monkeypatch, state, catalog, proposal
):
    proposal.update(chip="x3", x3_driver_id="6")
    middle = after_state(state, catalog, dict(proposal, chip=None, x3_driver_id=None))
    session = install(
        monkeypatch,
        tmp_path,
        [state, account.AccountError("unreadable"), middle],
        catalog,
    )
    with pytest.raises(DataError):
        account.apply(tmp_path, 2026, proposal)
    with pytest.raises(DataError, match="another scheduling window"):
        account.recover(
            tmp_path,
            2026,
            confirm_completed=False,
            scheduled={"account_binding": BINDING},
        )
    assert len(session.posts) == 1


def test_daemon_once_uses_shared_apply_headless_and_offline_status(
    setup, monkeypatch, capsys
):
    path, live, _, _, _, _ = setup
    monkeypatch.delenv("F1FANTASY_HEADLESS", raising=False)
    monkeypatch.setattr(account, "show", lambda *a: live)
    original = scheduler._tick
    monkeypatch.setattr(scheduler, "_tick", lambda *args: original(*args[:-1], now=NOW))

    def apply(options):
        assert os.environ["F1FANTASY_HEADLESS"] == "1"
        assert options.replan and options.scheduler_job["stage"] == "early"
        cli._json_output("account apply", dict(apply_status="unchanged"))

    monkeypatch.setattr(cli, "_account_command", apply)
    prefix = ["--season", "2026", "--account-dir", str(path)]
    assert cli.main(prefix + ["daemon", "run", "--once", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["status"] == "running"
    assert "F1FANTASY_HEADLESS" not in os.environ
    monkeypatch.setattr(account, "show", lambda *a: pytest.fail("offline"))
    assert cli.main(prefix + ["daemon", "status", "--format", "json"]) == 0


def test_daemon_sleep_does_not_lock_out_job_controls(setup, monkeypatch, capsys):
    path, live, _, _, _, _ = setup
    monkeypatch.setattr(account, "show", lambda *a: live)
    original = scheduler._tick
    monkeypatch.setattr(scheduler, "_tick", lambda *args: original(*args[:-1], now=NOW))
    monkeypatch.setattr(
        cli,
        "_account_command",
        lambda options: cli._json_output(
            "account apply", dict(apply_status="unchanged")
        ),
    )

    class StopAfterControl:
        stopped = False

        def set(self):
            self.stopped = True

        def is_set(self):
            return self.stopped

        def wait(self, seconds):
            final = next(
                j
                for j in scheduler.status(path)["jobs"].values()
                if j["stage"] == "final"
            )
            scheduler.change_job(path, final["id"], "cancel")
            self.set()

    monkeypatch.setattr(cli.threading, "Event", StopAfterControl)
    assert (
        cli.main(["--season", "2026", "--account-dir", str(path), "daemon", "run"]) == 0
    )
    assert any(
        j["status"] == "cancelled" for j in scheduler.status(path)["jobs"].values()
    )
