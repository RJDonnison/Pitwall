"""One-team, deadline-driven jobs; account journals own submission recovery."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import account
from .data import DataError


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise DataError(
            "Scheduler requires a timezone-bearing verified lock timestamp"
        ) from None


def validate(policy: dict) -> None:
    for name in ("early_hours", "final_minutes", "safety_seconds", "poll_seconds"):
        value = policy[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise DataError(f"Invalid scheduler {name}")
    if (
        policy["early_hours"] * 3600 <= policy["final_minutes"] * 60
        or policy["final_minutes"] * 60 <= policy["safety_seconds"]
    ):
        raise DataError(
            "Scheduler requires early run before final run before safety cutoff"
        )
    if not 1 <= policy["races"] <= 5:
        raise DataError("Scheduler planning horizon must be 1–5 races")


def directory(account_dir: Path) -> Path:
    return account_dir / "scheduler"


def _load(root: Path) -> dict:
    path = root / "state.json"
    value = (
        account._read_json(path)
        if path.exists()
        else {"version": 1, "jobs": {}, "events": []}
    )
    statuses = {
        "waiting",
        "running",
        "verified",
        "failed",
        "missed",
        "superseded",
        "cancelled",
    }
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("jobs"), dict)
        or not isinstance(value.get("events"), list)
    ):
        raise DataError(
            "Invalid scheduler state; inspect account audit before restarting"
        )
    for key, job in value["jobs"].items():
        if (
            not isinstance(job, dict)
            or job.get("id") != key
            or job.get("status") not in statuses
            or job.get("stage") not in {"early", "final", "final_fix"}
        ):
            raise DataError("Unrecognized scheduler job; no automatic replay")
        try:
            for name in ("season", "team_number", "gameday_id", "phase_id", "attempts"):
                account._integer(job[name], name)
            validate(job["policy"])
            if job["binding"] != value["binding"]:
                raise ValueError
            timestamp(job["due_at"])
            if job["stage"] != "final_fix":
                timestamp(job["deadline"])
                timestamp(job["cutoff_at"])
        except (KeyError, TypeError, ValueError):
            raise DataError(
                "Invalid persisted scheduler job; no automatic replay"
            ) from None
    return value


def status(account_dir: Path) -> dict:
    root = directory(account_dir)
    if not root.exists():
        return {"version": 1, "jobs": {}, "events": [], "status": "not_started"}
    return _load(root)


def _save(root: Path, state: dict) -> None:
    account._atomic(root / "state.json", state)


def _event(
    root: Path, state: dict, kind: str, now: datetime, notify, **details
) -> None:
    event = {
        "sequence": len(state["events"]) + 1,
        "at": now.isoformat(),
        "kind": kind,
        **details,
    }
    source = state["jobs"].get(details.get("job_id"), state)
    event.update(
        {
            key: source[key]
            for key in ("season", "team_number", "gameday_id", "phase_id")
            if key in source
        }
    )
    state["events"].append(event)
    _save(root, state)
    if notify is not None:
        try:
            notify(event)
        except (OSError, ValueError, RuntimeError):
            # Submission success must not become a failed submission because a
            # notification transport failed. The durable event remains readable.
            event["notification_error"] = (
                "Notification delivery failed; inspect daemon audit"
            )
            _save(root, state)


def _blocked(root, state, message, now, notify):
    if state.get("status") != "blocked" or state.get("reason") != message:
        state.update(status="blocked", reason=message)
        _event(root, state, "blocked", now, notify, message=message)
    else:
        _save(root, state)
    return state


def _job(state, live, stage, deadline, due, cutoff, policy):
    identity = [
        live["season"],
        live["team_number"],
        live["gameday_id"],
        live["phase_id"],
        stage,
        deadline,
    ]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    state["jobs"].setdefault(
        key,
        {
            "id": key,
            "stage": stage,
            "status": "waiting",
            "season": live["season"],
            "team_number": live["team_number"],
            "gameday_id": live["gameday_id"],
            "phase_id": live["phase_id"],
            "deadline": deadline,
            "due_at": due.isoformat(),
            "cutoff_at": cutoff.isoformat() if cutoff else None,
            "policy": policy.copy(),
            "attempts": 0,
            "binding": state["binding"],
        },
    )
    if state["jobs"][key]["status"] == "waiting":
        state["jobs"][key].update(
            due_at=due.isoformat(),
            cutoff_at=cutoff.isoformat() if cutoff else None,
            policy=policy.copy(),
        )
    return key


def tick(
    account_dir: Path,
    season: int,
    policy: dict,
    inspect,
    execute,
    *,
    notify=None,
    now=None,
) -> dict:
    """Run one polling cycle. Callbacks inspect fresh state and use verified apply."""
    validate(policy)
    with account._locked(directory(account_dir)) as root:
        return _tick(root, account_dir, season, policy, inspect, execute, notify, now)


def _tick(root, account_dir, season, policy, inspect, execute, notify, now=None):
    now = now or datetime.now(timezone.utc)
    state = _load(root)
    with account._locked(account_dir):
        binding = account._binding(account_dir, season)
    fingerprint = account._binding_fingerprint(binding)
    if state.get("binding") not in (None, fingerprint):
        raise DataError(
            "Scheduler account binding changed; use a separate account directory"
        )
    state.update(
        binding=fingerprint,
        checked_at=now.isoformat(),
        season=season,
        team_number=binding["team_number"],
    )
    try:
        live = inspect()
    except (DataError, OSError):
        return _blocked(
            root,
            state,
            "Fresh authenticated account state unavailable; reconnect or inspect account show",
            now,
            notify,
        )
    if live["season"] != season or live["team_number"] != binding["team_number"]:
        raise DataError("Scheduler inspected a different account team or season")
    current = (season, live["team_number"], live["gameday_id"], live["phase_id"])
    state.update(gameday_id=live["gameday_id"], phase_id=live["phase_id"])
    relevant = []
    reason = None
    window = live.get("final_fix_window", {})
    if (
        policy["final_fix_enabled"]
        and window.get("open")
        and "final_fix" in live["eligible_chips"]
    ):
        boundary = "final_fix:" + json.dumps(window, sort_keys=True)
        relevant.append(_job(state, live, "final_fix", boundary, now, None, policy))
    elif not live["locked"]:
        if not live.get("lock_deadline_utc"):
            reason = "Actual Fantasy lock deadline is unavailable; pre-lock submission is blocked (session start/countdown is not a deadline)"
        else:
            try:
                deadline = timestamp(live["lock_deadline_utc"])
            except DataError:
                reason = "Actual Fantasy lock deadline is invalid; pre-lock submission is blocked"
            else:
                end = deadline - timedelta(seconds=policy["safety_seconds"])
                final = deadline - timedelta(minutes=policy["final_minutes"])
                early = deadline - timedelta(hours=policy["early_hours"])
                stamp = deadline.isoformat()
                relevant.append(_job(state, live, "early", stamp, early, final, policy))
                relevant.append(_job(state, live, "final", stamp, final, end, policy))
    for job in state["jobs"].values():
        identity = tuple(
            job[name] for name in ("season", "team_number", "gameday_id", "phase_id")
        )
        if job["status"] == "running" and (
            job["id"] not in relevant or identity != current
        ):
            return _blocked(
                root,
                state,
                "An interrupted job no longer has a verified active window; inspect account audit and reconcile manually",
                now,
                notify,
            )
        if job["status"] in {"waiting", "running"} and (
            identity != current
            or (
                job["id"] not in relevant
                and (job["stage"] == "final_fix" or live.get("lock_deadline_utc"))
            )
        ):
            job["status"] = "superseded"
            _event(root, state, "superseded", now, notify, job_id=job["id"])
    if any(j["status"] == "failed" for j in state["jobs"].values()):
        return _blocked(
            root,
            state,
            "A scheduled job failed; inspect daemon/account audit and use daemon retry or cancel",
            now,
            notify,
        )
    if reason:
        return _blocked(root, state, reason, now, notify)
    state.update(status="running", reason=None)
    for key in relevant:
        job = state["jobs"][key]
        if job["status"] not in {"waiting", "running"}:
            continue
        if now < timestamp(job["due_at"]):
            continue
        if job["cutoff_at"] and now >= timestamp(job["cutoff_at"]):
            if job["status"] == "running":
                return _blocked(
                    root,
                    state,
                    "Interrupted job passed its cutoff; inspect account audit before any further scheduled action",
                    now,
                    notify,
                )
            job["status"] = "missed"
            _event(root, state, "missed", now, notify, job_id=key, stage=job["stage"])
            continue
        job.update(
            status="running", attempts=job["attempts"] + 1, started_at=now.isoformat()
        )
        _save(root, state)
        try:
            result = execute(job)
            if result.get("apply_status") not in {"verified", "unchanged"}:
                raise DataError("Scheduled account apply did not verify its result")
        except (DataError, OSError):
            job.update(
                status="failed",
                error="Account apply failed or is uncertain; inspect account audit before retrying",
            )
            _event(
                root,
                state,
                "failed",
                now,
                notify,
                job_id=key,
                stage=job["stage"],
                message=job["error"],
            )
            return _blocked(root, state, job["error"], now, notify)
        job.update(
            status="verified",
            finished_at=datetime.now(timezone.utc).isoformat(),
            apply_status=result["apply_status"],
            account_key=result.get("idempotency_key"),
        )
        _event(
            root,
            state,
            "verified",
            now,
            notify,
            job_id=key,
            stage=job["stage"],
            apply_status=result["apply_status"],
        )
    _save(root, state)
    return state


def change_job(account_dir: Path, job_id: str, action: str) -> dict:
    with account._locked(directory(account_dir)) as root:
        state = _load(root)
        job = state["jobs"].get(job_id)
        allowed = {"failed"} if action == "retry" else {"failed", "waiting", "running"}
        if action not in {"retry", "cancel"} or not job or job["status"] not in allowed:
            raise DataError("Job cannot be retried/cancelled in its current state")
        job.update(status="running" if action == "retry" else "cancelled", error=None)
        _event(root, state, action, datetime.now(timezone.utc), None, job_id=job_id)
        return job
