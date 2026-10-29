"""Offline scheduler behavior; no browser, Docker, or official submissions."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from f1fantasy import predict_scheduler as scheduler
from test_predict_account import public, api, live, proposal
from test_predict_account import install


@pytest.mark.parametrize("next_event", [False, True])
@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_failed_early_job_blocks_final_and_new_round_until_explicit_action(
    tmp_path, rig, next_event, action
):
    current, recommend, posts, calls, _, _ = rig

    def failed(_):
        raise RuntimeError("model/preflight failure")

    result = scheduler.tick(tmp_path, 2026, POLICY, failed, now=NOW)
    early = stages(result)["early"]
    assert result["status"] == "blocked"
    assert "retry" in result["reason"]
    if next_event:
        current.update(gameday_id=20, race_id=7500)
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(hours=23, minutes=45)
    )
    assert result["status"] == "blocked"
    assert len(result["jobs"]) == 2
    assert not posts and not calls
    getattr(scheduler, action)(tmp_path, early["id"])
    assert scheduler.status(tmp_path)["status"] == "active"
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(hours=23, minutes=45)
    )
    assert result["status"] == "active"
    assert len(posts) == len(calls) == 1


def test_scheduler_pending_manual_journal_cannot_resume_different_answers(
    monkeypatch, tmp_path, public
):
    session, account_root = install(monkeypatch, tmp_path, live(public))
    monkeypatch.setattr(scheduler.account, "_now", lambda: NOW)
    manual = proposal(session.current)
    manual["answers"][1]["selected_options"] = ["2"]
    manual["answers"][2]["selected_options"] = ["3"]
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        scheduler.account.apply(tmp_path, 2026, manual)
    session.after = None
    session.posts.clear()
    monkeypatch.setattr(
        scheduler.account, "show", lambda *a, **k: deepcopy(session.current)
    )

    def recommend(snapshot):
        result = proposal(snapshot)
        result["answers"][3]["selected_options"] = ["4"]
        return result

    def uncertain(*args):
        raise scheduler.SchedulerError("uncertain scheduler attempt")

    monkeypatch.setattr(scheduler.account, "apply", uncertain)
    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert result["status"] == "blocked"
    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert result["status"] == "blocked"
    assert stages(result)["early"]["status"] == "unknown"
    assert session.posts == []
    assert [
        s["status"] for s in scheduler.account._journal(account_root)[0]["steps"]
    ] == ["prepared", "ready"]


NOW = datetime(2099, 10, 30, 21, tzinfo=timezone.utc)
POLICY = {"early_hours": 24, "final_minutes": 15, "safety_seconds": 90}


@pytest.fixture
def rig(monkeypatch, public):
    state = live(public)
    posts, recommendations, notifications, recoveries = [], [], [], []
    monkeypatch.setattr(
        scheduler.account, "show", lambda *args, **kwargs: deepcopy(state)
    )
    monkeypatch.setattr(scheduler.account, "_now", lambda: NOW)

    def recommend(snapshot):
        recommendations.append(deepcopy(snapshot))
        target = proposal(snapshot)
        target["answers"][1]["selected_options"] = ["2"]
        return target

    def apply(*args):
        target = args[-1]
        posts.append(deepcopy(target))
        state["answers"] = deepcopy(target["answers"])
        return {**deepcopy(state), "apply_status": "verified"}

    def recover(*args, **kwargs):
        recoveries.append(kwargs)
        return {**deepcopy(state), "apply_status": "verified"}

    monkeypatch.setattr(scheduler.account, "apply", apply)
    monkeypatch.setattr(scheduler.account, "recover", recover)
    return state, recommend, posts, recommendations, notifications, recoveries


def stages(state):
    return {job["stage"]: job for job in state["jobs"].values()}


def test_early_and_final_each_once_with_fresh_recommendation(tmp_path, rig):
    _, recommend, posts, calls, notifications, _ = rig
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, notify=notifications.append, now=NOW
    )
    assert stages(result)["early"]["status"] == "verified"
    assert stages(result)["final"]["status"] == "waiting"
    scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert len(posts) == len(calls) == 1
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(hours=23, minutes=45)
    )
    assert stages(result)["final"]["status"] == "verified"
    assert len(posts) == len(calls) == 2
    assert notifications[-1]["kind"] == "verified"
    assert scheduler.audit(tmp_path)[0]["kind"] == "running"


@pytest.mark.parametrize("damage", ["deadline", "authority", "locked", "cutoff"])
def test_no_mutation_without_remote_window(tmp_path, rig, damage):
    current, recommend, posts, calls, _, _ = rig
    now = NOW
    if damage == "deadline":
        current["deadline_utc"] = None
    elif damage == "authority":
        current["deadline_authority"] = "user-override"
    elif damage == "locked":
        current["locked"] = True
    else:
        now += timedelta(hours=24, seconds=-90)
    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, now=now)
    assert not posts and not calls
    if damage in {"deadline", "authority"}:
        assert result["status"] == "blocked"
    else:
        assert all(j["status"] == "missed" for j in result["jobs"].values())


def test_late_first_poll_supersedes_early_stage(tmp_path, rig):
    _, recommend, posts, _, _, _ = rig
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(hours=23, minutes=46)
    )
    assert stages(result)["early"]["status"] == "superseded"
    assert stages(result)["final"]["status"] == "verified"
    assert len(posts) == 1


def test_preflight_failure_retry_and_cancel_are_explicit(tmp_path, rig):
    _, recommend, posts, _, _, _ = rig

    def failing(_):
        raise scheduler.SchedulerError("private model error must not be logged")

    result = scheduler.tick(tmp_path, 2026, POLICY, failing, now=NOW)
    job = stages(result)["early"]
    assert job["status"] == "failed"
    scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert not posts
    scheduler.retry(tmp_path, job["id"])
    scheduler.cancel(tmp_path, job["id"])
    scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert not posts
    with pytest.raises(scheduler.SchedulerError):
        scheduler.retry(tmp_path, job["id"])
    assert "private model error" not in str(scheduler.audit(tmp_path))


def test_unknown_apply_recovers_before_new_model_or_deadline_gate(
    monkeypatch, tmp_path, rig
):
    current, recommend, posts, calls, _, recoveries = rig

    def uncertain(*args):
        target = args[-1]
        current["answers"] = deepcopy(target["answers"])
        posts.append(target)
        raise scheduler.SchedulerError("timeout")

    monkeypatch.setattr(scheduler.account, "apply", uncertain)
    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    job = stages(result)["early"]
    assert job["status"] == "unknown"
    assert result["status"] == "blocked"
    assert "unresolved" in result["reason"]
    with pytest.raises(scheduler.SchedulerError):
        scheduler.retry(tmp_path, job["id"])
    with pytest.raises(scheduler.SchedulerError):
        scheduler.cancel(tmp_path, job["id"])
    current.update(deadline_utc=None, deadline_authority=None, locked=True)
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(days=1)
    )
    assert stages(result)["early"]["status"] == "verified"
    assert len(posts) == len(calls) == len(recoveries) == 1
    assert recoveries[0]["expected"]["answers"] == job["expected_answers"]
    assert recoveries[0]["expected"]["binding_fingerprint"] == job["binding"]
    assert recoveries[0]["expected"]["race_id"] == job["race_id"]
    assert result["status"] == "active"


def test_restart_running_job_is_not_resubmitted(monkeypatch, tmp_path, rig):
    current, recommend, _, calls, _, recoveries = rig

    def crash(*args):
        current["answers"] = deepcopy(args[-1]["answers"])
        raise KeyboardInterrupt

    monkeypatch.setattr(scheduler.account, "apply", crash)
    with pytest.raises(KeyboardInterrupt):
        scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert stages(scheduler.status(tmp_path))["early"]["status"] == "running"
    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert stages(result)["early"]["status"] == "verified"
    assert len(calls) == len(recoveries) == 1


def test_unresolved_recovery_blocks_all_new_jobs(monkeypatch, tmp_path, rig):
    _, recommend, _, calls, _, _ = rig
    monkeypatch.setattr(
        scheduler.account,
        "apply",
        lambda *a: (_ for _ in ()).throw(scheduler.SchedulerError("unknown")),
    )
    scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    monkeypatch.setattr(
        scheduler.account,
        "recover",
        lambda *a, **k: (_ for _ in ()).throw(
            scheduler.SchedulerError("still unknown")
        ),
    )
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(hours=23, minutes=45)
    )
    assert result["status"] == "blocked"
    assert len(calls) == 1


def test_deadline_change_supersedes_waiting_jobs(tmp_path, rig):
    current, recommend, posts, _, _, _ = rig
    first = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW - timedelta(hours=1)
    )
    original_keys = set(first["jobs"])
    current["deadline_utc"] = "2099-11-01T21:00:00+00:00"
    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    assert all(result["jobs"][k]["status"] == "superseded" for k in original_keys)
    assert not posts


def test_bonus_is_separate_explicit_scope(tmp_path, rig):
    current, recommend, _, _, _, _ = rig
    current.update(scope="season", gameday_id=25, race_id=7424)
    result = scheduler.tick(
        tmp_path, 2026, {**POLICY, "scope": "season"}, recommend, now=NOW
    )
    assert all(
        j["scope"] == "season" and j["gameday_id"] == 25
        for j in result["jobs"].values()
    )
    with pytest.raises(scheduler.SchedulerError, match="different season/scope"):
        scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)


def test_binding_change_refuses_existing_jobs(tmp_path, rig):
    current, recommend, _, _, _, _ = rig
    scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW - timedelta(hours=1))
    current["binding_fingerprint"] = "different-account"
    with pytest.raises(scheduler.SchedulerError, match="binding changed"):
        scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)


def test_forecast_preflight_detects_official_changes(tmp_path, rig):
    current, recommend, posts, _, _, _ = rig

    def changes(snapshot):
        target = recommend(snapshot)
        current["question_fingerprint"] = "changed-points"
        return target

    result = scheduler.tick(tmp_path, 2026, POLICY, changes, now=NOW)
    assert stages(result)["early"]["status"] == "failed"
    assert not posts


def test_model_runtime_cannot_cross_safety_cutoff(monkeypatch, tmp_path, rig):
    _, recommend, posts, _, _, _ = rig
    ticks = iter([0, 31])
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: next(ticks))
    result = scheduler.tick(
        tmp_path, 2026, POLICY, recommend, now=NOW + timedelta(hours=24, seconds=-120)
    )
    assert stages(result)["final"]["status"] == "failed"
    assert not posts


def test_notification_error_does_not_undo_verified_apply(tmp_path, rig):
    _, recommend, posts, _, _, _ = rig

    def notify(_):
        raise RuntimeError("sensitive webhook url")

    result = scheduler.tick(tmp_path, 2026, POLICY, recommend, notify=notify, now=NOW)
    assert stages(result)["early"]["status"] == "verified"
    assert len(posts) == 1
    assert "sensitive webhook" not in str(result)
    assert result["events"][-1]["notification_error"]


@pytest.mark.parametrize(
    "policy",
    [
        {},
        {**POLICY, "safety_seconds": float("nan")},
        {**POLICY, "final_minutes": 1},
        {**POLICY, "early_hours": True},
        {**POLICY, "scope": "both"},
    ],
)
def test_invalid_policy(policy):
    with pytest.raises(scheduler.SchedulerError):
        scheduler.validate(policy)


def test_store_integrity_and_scheduler_lock(tmp_path, rig):
    _, recommend, _, _, _, _ = rig
    scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW - timedelta(hours=1))
    root = scheduler._root(tmp_path)
    assert (root / "state.json").stat().st_mode & 0o777 == 0o600
    with scheduler.security._locked(root):
        with pytest.raises(scheduler.security.AccountError, match="Another"):
            scheduler.tick(tmp_path, 2026, POLICY, recommend, now=NOW)
    data = scheduler.status(tmp_path)
    data["jobs"] = {}
    scheduler.security._atomic(root / "state.json", data)
    with pytest.raises(scheduler.SchedulerError, match="integrity"):
        scheduler.status(tmp_path)
