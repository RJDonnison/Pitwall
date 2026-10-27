"""Deadline authority, durable job identity and unattended no-replay boundaries."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

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
ACCOUNT_BINDING = account._binding_fingerprint(
    dict(guid="account-identity", season=2026, team_number=2)
)


def test_daemon_once_runs_headless_shared_apply_and_restores_environment(
    setup, monkeypatch, capsys
):
    import os

    path, live, _, _, _, _ = setup
    monkeypatch.delenv("F1FANTASY_HEADLESS", raising=False)
    monkeypatch.setattr(account, "show", lambda *a: live)
    original_tick = scheduler._tick
    monkeypatch.setattr(scheduler, "_tick", lambda *args: original_tick(*args, now=NOW))

    def apply(options):
        assert os.environ["F1FANTASY_HEADLESS"] == "1"
        assert options.replan is True and options.chips is True and options.races == 3
        assert options.scheduler_job["stage"] == "early"
        assert options.scheduled["deadline"] == live["lock_deadline_utc"]
        cli._json_output("account apply", {"apply_status": "unchanged"})
        return 0

    monkeypatch.setattr(cli, "_account_command", apply)
    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--account-dir",
                str(path),
                "daemon",
                "run",
                "--once",
                "--format",
                "json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)["data"]
    assert any(
        j["apply_status"] == "unchanged"
        for j in result["jobs"].values()
        if j["status"] == "verified"
    )
    assert "F1FANTASY_HEADLESS" not in os.environ


def test_waiting_job_adopts_changed_timing_but_running_plan_does_not(setup):
    _, live, policy, calls, _, tick = setup
    live["lock_deadline_utc"] = (NOW + timedelta(days=2)).isoformat()
    tick()
    assert not calls
    policy["early_hours"] = 60
    tick()
    assert calls[0]["policy"]["early_hours"] == 60


def test_cutoff_crossing_during_durable_prepare_prevents_post(
    tmp_path, monkeypatch, state, catalog, proposal
):
    clock = [NOW]
    monkeypatch.setattr(account, "_now", lambda: clock[0])
    state["lock_deadline_utc"] = (NOW + timedelta(hours=1)).isoformat()
    cutoff = NOW + timedelta(minutes=55)
    proposal["scheduled"] = dict(
        team_number=2,
        account_binding=ACCOUNT_BINDING,
        phase_id=1,
        deadline=state["lock_deadline_utc"],
        cutoff=cutoff.isoformat(),
    )
    session = install(monkeypatch, tmp_path, [state], catalog)
    save = account._save_ledger

    def prepare(directory, rows):
        save(directory, rows)
        clock[0] = cutoff + timedelta(seconds=1)

    monkeypatch.setattr(account, "_save_ledger", prepare)
    with pytest.raises(DataError, match="safety cutoff"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == []
    assert account._ledger(tmp_path)[0]["status"] == "prepared"


def test_combined_chip_is_not_spent_if_safety_cutoff_passes_after_lineup(
    tmp_path, monkeypatch, state, catalog, proposal
):
    clock = [NOW]
    monkeypatch.setattr(account, "_now", lambda: clock[0])
    state["lock_deadline_utc"] = (NOW + timedelta(hours=1)).isoformat()
    proposal.update(chip="x3", x3_driver_id="6")
    middle = after_state(state, catalog, dict(proposal, chip=None, x3_driver_id=None))
    cutoff = NOW + timedelta(minutes=55)
    proposal["scheduled"] = dict(
        team_number=2,
        account_binding=ACCOUNT_BINDING,
        phase_id=1,
        deadline=state["lock_deadline_utc"],
        cutoff=cutoff.isoformat(),
    )
    session = install(monkeypatch, tmp_path, [state, middle], catalog)
    post = session.post

    def save_lineup(*args):
        post(*args)
        clock[0] = cutoff + timedelta(seconds=1)

    session.post = save_lineup
    with pytest.raises(DataError, match="safety cutoff"):
        account.apply(tmp_path, 2026, proposal)
    assert [path.rsplit("/", 1)[-1] for path, _ in session.posts] == ["transferteam"]


@pytest.fixture
def setup(tmp_path):
    account._atomic(
        tmp_path / "binding.json",
        {"guid": "test-guid", "season": 2026, "team_number": 2},
    )
    live = {
        "season": 2026,
        "team_number": 2,
        "gameday_id": 19,
        "phase_id": 1,
        "locked": False,
        "eligible_chips": [],
        "lock_deadline_utc": (NOW + timedelta(hours=12)).isoformat(),
    }
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
        return {"apply_status": "verified", "idempotency_key": "account-job-key"}

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


def test_early_then_final_are_once_each_across_restarts(setup):
    path, live, _, calls, events, tick = setup
    value = tick()
    assert [j["stage"] for j in calls] == ["early"]
    assert tick()["jobs"] == value["jobs"]
    deadline = scheduler.timestamp(live["lock_deadline_utc"])
    tick(deadline - timedelta(minutes=14))
    tick(deadline - timedelta(minutes=10))
    assert [j["stage"] for j in calls] == ["early", "final"]
    assert len([e for e in events if e["kind"] == "verified"]) == 2
    assert (path / "scheduler" / "state.json").stat().st_mode & 0o777 == 0o600
    assert "test-guid" not in json.dumps(scheduler.status(path))


def test_restart_near_lock_skips_early_and_runs_final_only(setup):
    _, live, _, calls, _, tick = setup
    value = tick(scheduler.timestamp(live["lock_deadline_utc"]) - timedelta(minutes=10))
    assert [j["stage"] for j in calls] == ["final"]
    assert any(
        j["stage"] == "early" and j["status"] == "missed"
        for j in value["jobs"].values()
    )


@pytest.mark.parametrize("deadline", [None, "0", "2026-10-30T12:00:00"])
def test_missing_actual_deadline_never_falls_back_to_session_time(setup, deadline):
    _, live, _, calls, events, tick = setup
    live.update(
        lock_deadline_utc=deadline,
        first_session_utc=(NOW + timedelta(hours=12)).isoformat(),
    )
    assert tick()["status"] == "blocked"
    assert tick()["status"] == "blocked"
    assert calls == [] and len(events) == 1


def test_deadline_reschedule_supersedes_old_waiting_jobs(setup):
    _, live, _, calls, _, tick = setup
    first = tick()
    old_final = next(j["id"] for j in first["jobs"].values() if j["stage"] == "final")
    live["lock_deadline_utc"] = (NOW + timedelta(days=2)).isoformat()
    value = tick()
    assert value["jobs"][old_final]["status"] == "superseded"
    assert len(calls) == 1
    tick(NOW + timedelta(hours=30))
    assert [j["stage"] for j in calls] == ["early", "early"]


def test_no_submissions_inside_safety_cutoff_or_when_locked(setup):
    _, live, _, calls, _, tick = setup
    value = tick(scheduler.timestamp(live["lock_deadline_utc"]) - timedelta(seconds=30))
    assert all(j["status"] == "missed" for j in value["jobs"].values())
    live["locked"] = True
    tick()
    assert not calls


def test_final_fix_uses_authoritative_window_without_prelock_timestamp(setup):
    _, live, _, calls, _, tick = setup
    live.update(
        locked=True,
        lock_deadline_utc=None,
        eligible_chips=["final_fix"],
        final_fix_window={"open": True, "raceday": 44, "race_category": "R"},
    )
    tick()
    tick()
    assert [j["stage"] for j in calls] == ["final_fix"]
    live["final_fix_window"]["open"] = False
    tick()
    assert len(calls) == 1


def test_failed_job_blocks_later_stage_until_explicit_retry(setup):
    path, live, _, calls, _, tick = setup

    def fail(job):
        raise DataError("Do not leak an arbitrary service response")

    value = tick(runner=fail)
    failed = next(j for j in value["jobs"].values() if j["status"] == "failed")
    assert value["status"] == "blocked"
    assert tick()["status"] == "blocked" and not calls
    assert "arbitrary service" not in json.dumps(value)
    scheduler.change_job(path, failed["id"], "retry")
    tick()
    assert len(calls) == 1
    assert scheduler.status(path)["jobs"][failed["id"]]["status"] == "verified"


def test_interrupted_running_job_resumes_same_id_and_policy(setup):
    path, _, policy, calls, _, tick = setup

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


def test_notification_failure_cannot_reclassify_verified_submission(setup):
    path, live, policy, calls, _, _ = setup

    def notify(event):
        raise RuntimeError("external notification failed")

    value = scheduler.tick(
        path,
        2026,
        policy,
        lambda: live,
        lambda job: {"apply_status": "unchanged"},
        notify=notify,
        now=NOW,
    )
    assert any(j["status"] == "verified" for j in value["jobs"].values())
    assert value["events"][-1]["notification_error"]


def test_binding_changes_never_retarget_an_existing_daemon(setup):
    path, _, _, _, _, tick = setup
    tick()
    account._atomic(
        path / "binding.json", {"guid": "other-guid", "season": 2026, "team_number": 2}
    )
    with pytest.raises(DataError, match="binding changed"):
        tick()


@pytest.mark.parametrize(
    "key,value",
    [
        ("early_hours", float("nan")),
        ("final_minutes", 1),
        ("poll_seconds", 0),
        ("races", 6),
    ],
)
def test_invalid_policy_does_not_start_jobs(setup, key, value):
    _, _, policy, calls, _, tick = setup
    policy[key] = value
    with pytest.raises(DataError):
        tick()
    assert not calls


@pytest.mark.parametrize(
    "change", ["deadline", "cutoff", "team_number", "phase_id", "account_binding"]
)
def test_scheduled_apply_revalidates_guard_before_any_write(
    tmp_path, monkeypatch, state, catalog, proposal, change
):
    monkeypatch.setattr(account, "_now", lambda: NOW)
    state["lock_deadline_utc"] = (NOW + timedelta(hours=1)).isoformat()
    proposal["scheduled"] = dict(
        team_number=2,
        account_binding=ACCOUNT_BINDING,
        phase_id=1,
        deadline=state["lock_deadline_utc"],
        cutoff=(NOW + timedelta(minutes=55)).isoformat(),
    )
    if change in {"team_number", "phase_id"}:
        proposal["scheduled"][change] += 1
    elif change == "deadline":
        proposal["scheduled"][change] = (NOW + timedelta(hours=2)).isoformat()
    elif change == "account_binding":
        proposal["scheduled"][change] = "0" * 64
    else:
        proposal["scheduled"][change] = (NOW - timedelta(seconds=1)).isoformat()
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(DataError, match="Scheduled"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == [] and not (tmp_path / "journal.json").exists()


def test_daemon_status_and_audit_are_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(account, "show", lambda *a: pytest.fail("offline"))
    assert (
        cli.main(
            ["--account-dir", str(tmp_path), "daemon", "status", "--format", "json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["status"] == "not_started"
    assert (
        cli.main(
            ["--account-dir", str(tmp_path), "daemon", "audit", "--format", "json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["events"] == []


def test_closed_final_fix_window_blocks_interrupted_job_instead_of_forgetting_it(setup):
    _, live, _, calls, _, tick = setup
    live.update(
        locked=True,
        eligible_chips=["final_fix"],
        final_fix_window={"open": True, "raceday": 44},
    )

    def crash(job):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tick(runner=crash)
    live["final_fix_window"]["open"] = False
    assert tick()["status"] == "blocked"
    assert not calls


def test_cancel_failed_job_does_not_clear_account_journal(setup):
    path, _, _, _, _, tick = setup

    def fail(job):
        raise DataError("unknown outcome")

    result = tick(runner=fail)
    job = next(j for j in result["jobs"].values() if j["status"] == "failed")
    account._atomic(
        path / "journal.json", [{"status": "unknown", "unchanged_marker": 1}]
    )
    scheduler.change_job(path, job["id"], "cancel")
    assert scheduler.status(path)["jobs"][job["id"]]["status"] == "cancelled"
    assert account._read_json(path / "journal.json") == [
        {"status": "unknown", "unchanged_marker": 1}
    ]


def test_expired_login_is_reported_without_attempting_jobs(setup):
    path, _, policy, calls, events, _ = setup

    def expired():
        raise account.AccountError("expired login")

    result = scheduler.tick(
        path,
        2026,
        policy,
        expired,
        lambda job: calls.append(job),
        notify=events.append,
        now=NOW,
    )
    assert result["status"] == "blocked"
    assert "reconnect" in result["reason"] and not calls


def test_unrecognized_saved_job_does_not_replay(setup):
    path, _, _, calls, _, tick = setup
    value = tick()
    key = next(iter(value["jobs"]))
    value["jobs"][key]["status"] = "unsupported_future_status"
    account._atomic(path / "scheduler" / "state.json", value)
    with pytest.raises(DataError, match="no automatic replay"):
        tick()
    assert len(calls) == 1


def test_repeated_blocked_poll_updates_heartbeat_without_duplicate_notification(setup):
    path, live, _, _, events, tick = setup
    live["lock_deadline_utc"] = None
    tick()
    later = NOW + timedelta(minutes=2)
    tick(now=later)
    assert scheduler.status(path)["checked_at"] == later.isoformat()
    assert len(events) == 1
