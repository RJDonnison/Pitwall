"""Bounded early/final Predict jobs; account journals own answer recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
from pathlib import Path

from . import account as security
from . import predict_account as account

SchedulerError = account.PredictAccountError


def _root(directory):
    return account.storage_directory(directory) / "scheduler"


def validate(policy):
    if not isinstance(policy, dict):
        raise SchedulerError("Predict scheduling policy must be an object")
    for name in ("early_hours", "final_minutes", "safety_seconds"):
        value = policy.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise SchedulerError(f"Invalid Predict scheduler {name}")
    if (
        not policy["early_hours"] * 3600
        > policy["final_minutes"] * 60
        > policy["safety_seconds"]
    ):
        raise SchedulerError(
            "Predict stages require early before final before safety cutoff"
        )
    if policy.get("scope", "round") not in {"round", "season"}:
        raise SchedulerError("Predict season bonus requires explicit season scope")


def _load(root):
    path = root / "state.json"
    if not path.exists():
        return {"version": 1, "jobs": {}, "events": []}
    state = security._read_json(path)
    try:
        if state["version"] != 1 or state["checksum"] != security._checksum(state):
            raise ValueError
        if not isinstance(state["jobs"], dict) or not isinstance(state["events"], list):
            raise ValueError
        for key, job in state["jobs"].items():
            if job["id"] != key or job["status"] not in {
                "waiting",
                "running",
                "verified",
                "failed",
                "unknown",
                "missed",
                "cancelled",
                "superseded",
            }:
                raise ValueError
            if job["stage"] not in {"early", "final"} or job["scope"] not in {
                "round",
                "season",
            }:
                raise ValueError
            for name in ("due_at", "deadline", "cutoff_at"):
                account._timestamp(job[name])
    except (KeyError, TypeError, ValueError):
        raise SchedulerError(
            "Invalid Predict scheduler state integrity; no automatic replay"
        ) from None
    return state


def _save(root, state):
    state["checksum"] = security._checksum(state)
    security._atomic(root / "state.json", state)


def _event(root, state, kind, now, notify=None, **details):
    event = {
        "sequence": len(state["events"]) + 1,
        "at": now.isoformat(),
        "kind": kind,
        **details,
    }
    state["events"].append(event)
    _save(root, state)
    if notify:
        try:
            notify(event.copy())
        except Exception:
            event["notification_error"] = "Predict notification delivery failed"
            _save(root, state)


def status(directory: Path) -> dict:
    with security._locked(_root(directory)) as root:
        return _load(root)


def audit(directory: Path) -> list[dict]:
    return status(directory)["events"]


def _blocked(root, state, reason, now, notify):
    changed = state.get("status") != "blocked" or state.get("reason") != reason
    state.update(status="blocked", reason=reason, checked_at=now.isoformat())
    if changed:
        _event(root, state, "blocked", now, notify, reason=reason)
    else:
        _save(root, state)
    return state


def tick(
    directory: Path, season: int, policy: dict, recommend, notify=None, now=None
) -> dict:
    """Inspect a fresh official round and run at most one due stage per tick.

    ``recommend(live_snapshot)`` must return a complete account recommendation.
    Optional ``policy.scope='season'`` opts into a separate bonus event. No
    scheduling deadline can be supplied in policy or by the callback.
    """
    validate(policy)
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise SchedulerError("Predict scheduler now must be timezone aware")
    now = now.astimezone(timezone.utc)
    scope = policy.get("scope", "round")
    with security._locked(_root(directory)) as root:
        state = _load(root)
        try:
            live = account.show(directory, season, scope=scope)
        except (ValueError, OSError):
            return _blocked(
                root,
                state,
                "Fresh authenticated Predict state unavailable",
                now,
                notify,
            )
        if live["season"] != season or live["scope"] != scope:
            raise SchedulerError("Predict scheduler observed a different season/scope")
        binding = live["binding_fingerprint"]
        if state.get("binding") not in (None, binding):
            raise SchedulerError(
                "Predict scheduler binding changed; use separate storage"
            )
        state.update(binding=binding, checked_at=now.isoformat())

        # Process-restart/uncertain outcomes are reconciled before deadline gates.
        # Never ask the model for a new proposal while a job may have submitted.
        uncertain = [
            j for j in state["jobs"].values() if j["status"] in {"running", "unknown"}
        ]
        if uncertain:
            job = uncertain[0]
            try:
                with account._safety_cutoff(account._timestamp(job["cutoff_at"])):
                    result = account.recover(
                        directory,
                        season,
                        gameday_id=job["gameday_id"],
                        scope=job["scope"],
                        expected={
                            "binding_fingerprint": job["binding"],
                            **{
                                key: job[key]
                                for key in ("season", "gameday_id", "race_id", "scope")
                            },
                            "answers": job["expected_answers"],
                            **(
                                {"question_fingerprint": job["question_fingerprint"]}
                                if "question_fingerprint" in job
                                else {}
                            ),
                        },
                    )
                if result.get("apply_status") != "verified" or result.get(
                    "answers"
                ) != job.get("expected_answers"):
                    raise SchedulerError("No matching verified account journal")
            except Exception:
                job["status"] = "unknown"
                return _blocked(
                    root,
                    state,
                    "Predict submission outcome unresolved; inspect account recovery",
                    now,
                    notify,
                )
            job["status"] = "verified"
            if any(j["status"] == "failed" for j in state["jobs"].values()):
                return _blocked(
                    root,
                    state,
                    "A Predict job failed; retry or cancel it before further work",
                    now,
                    notify,
                )
            state.update(status="active", reason=None)
            _event(
                root, state, "verified", now, notify, job_id=job["id"], recovered=True
            )
            return state

        if any(j["status"] == "failed" for j in state["jobs"].values()):
            return _blocked(
                root,
                state,
                "A Predict job failed; retry or cancel it before further work",
                now,
                notify,
            )

        if live.get("deadline_authority") != account.AUTHORITY or not live.get(
            "deadline_utc"
        ):
            return _blocked(
                root, state, "No authoritative exact Predict lock deadline", now, notify
            )
        deadline = account._timestamp(live["deadline_utc"])
        cutoff = deadline - timedelta(seconds=policy["safety_seconds"])
        event = {
            k: live[k]
            for k in ("season", "scope", "gameday_id", "race_id", "deadline_utc")
        }
        relevant = []
        for stage, due in (
            ("early", deadline - timedelta(hours=policy["early_hours"])),
            ("final", deadline - timedelta(minutes=policy["final_minutes"])),
        ):
            key = account._digest({"binding": binding, **event, "stage": stage})
            relevant.append(key)
            state["jobs"].setdefault(
                key,
                {
                    "id": key,
                    "binding": binding,
                    "stage": stage,
                    "status": "waiting",
                    **event,
                    "deadline": deadline.isoformat(),
                    "cutoff_at": cutoff.isoformat(),
                    "due_at": due.isoformat(),
                    "attempts": 0,
                },
            )
            job = state["jobs"][key]
            if job["status"] == "waiting":
                job.update(due_at=due.isoformat(), cutoff_at=cutoff.isoformat())
        for key, job in state["jobs"].items():
            if (
                job["scope"] == scope
                and key not in relevant
                and job["status"] == "waiting"
            ):
                job["status"] = "superseded"
        state.update(status="active", reason=None)
        if live["locked"] or now >= cutoff:
            for key in relevant:
                if state["jobs"][key]["status"] == "waiting":
                    state["jobs"][key]["status"] = "missed"
            _event(
                root,
                state,
                "cutoff",
                now,
                notify,
                gameday_id=live["gameday_id"],
                scope=scope,
            )
            return state
        due = [
            state["jobs"][key]
            for key in relevant
            if state["jobs"][key]["status"] == "waiting"
            and now >= account._timestamp(state["jobs"][key]["due_at"])
        ]
        # A late first poll in the final window must not run stale early work.
        if len(due) == 2:
            due[0]["status"] = "superseded"
        if not due:
            _save(root, state)
            return state
        job = due[-1]
        started = time.monotonic()
        _save(root, state)
        try:
            proposal = recommend(live)
            proposal = account._recommendation(proposal, live)
            # Model runtime cannot extend the safety window. Refresh all official
            # metadata/account inputs before transitioning the job to running.
            refreshed = account.show(
                directory, season, gameday_id=live["gameday_id"], scope=scope
            )
            if (
                account._frame(refreshed) != account._frame(live)
                or refreshed["answers"] != live["answers"]
                or refreshed["binding_fingerprint"] != binding
            ):
                raise SchedulerError("Predict state changed during recommendation")
            account._writable(refreshed)
            # For injected clocks preserve elapsed wall time rather than replacing
            # the test/poll clock with an unrelated real-world instant.
            if now + timedelta(seconds=math.ceil(time.monotonic() - started)) >= cutoff:
                raise SchedulerError(
                    "Predict safety cutoff reached during recommendation"
                )
        except Exception:
            job["status"] = "failed"
            state.update(
                status="blocked",
                reason="Predict recommendation/preflight failed; explicit retry or cancel required",
            )
            _event(
                root,
                state,
                "failed",
                now,
                notify,
                job_id=job["id"],
                reason="Fresh recommendation/preflight failed; explicit retry required",
            )
            return state
        job.update(
            status="running",
            attempts=job["attempts"] + 1,
            expected_answers=proposal["answers"],
            question_fingerprint=proposal["question_fingerprint"],
        )
        _event(root, state, "running", now, notify, job_id=job["id"])
        try:
            with account._safety_cutoff(cutoff, expected=refreshed):
                result = account.apply(directory, season, proposal)
            if (
                result.get("apply_status") != "verified"
                or result["answers"] != proposal["answers"]
            ):
                raise SchedulerError("Predict apply not verified")
        except Exception:
            job["status"] = "unknown"
            state.update(
                status="blocked",
                reason="Predict submission outcome unresolved; inspect account recovery",
            )
            _event(
                root,
                state,
                "unknown",
                now,
                notify,
                job_id=job["id"],
                reason="Use account readback recovery; no automatic resubmission",
            )
            return state
        job["status"] = "verified"
        state.update(status="active", reason=None)
        _event(root, state, "verified", now, notify, job_id=job["id"])
        return state


def retry(directory: Path, job_id: str) -> dict:
    """Requeue preflight failures only; uncertain writes require recovery."""
    with security._locked(_root(directory)) as root:
        state = _load(root)
        job = state["jobs"].get(job_id)
        if not job or job["status"] != "failed":
            raise SchedulerError(
                "Only failed pre-submission Predict jobs may be retried"
            )
        job["status"] = "waiting"
        if not any(
            j["status"] in {"failed", "unknown", "running"}
            for j in state["jobs"].values()
        ):
            state.update(status="active", reason=None)
        _event(root, state, "retry", datetime.now(timezone.utc), job_id=job_id)
        return job


def cancel(directory: Path, job_id: str) -> dict:
    """Cancel unsent work. Never hide an uncertain account write."""
    with security._locked(_root(directory)) as root:
        state = _load(root)
        job = state["jobs"].get(job_id)
        if not job or job["status"] not in {"waiting", "failed"}:
            raise SchedulerError("Only unsent Predict jobs may be cancelled")
        job["status"] = "cancelled"
        if not any(
            j["status"] in {"failed", "unknown", "running"}
            for j in state["jobs"].values()
        ):
            state.update(status="active", reason=None)
        _event(root, state, "cancelled", datetime.now(timezone.utc), job_id=job_id)
        return job
