"""Illustrative offline contracts, not authenticated production captures."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from f1fantasy import predict_account as account


def recovery_target(snapshot):
    return {
        **{
            key: snapshot[key]
            for key in (
                "binding_fingerprint",
                "season",
                "gameday_id",
                "race_id",
                "scope",
                "question_fingerprint",
            )
        },
        "answers": deepcopy(snapshot["answers"]),
    }


@pytest.mark.parametrize(
    "mismatch",
    [
        "answers",
        "binding_fingerprint",
        "race_id",
        "gameday_id",
        "season",
        "scope",
        "question_fingerprint",
    ],
)
def test_expected_recovery_rejects_manual_pending_target_before_any_ready_step(
    monkeypatch, tmp_path, public, mismatch
):
    session, _ = install(monkeypatch, tmp_path, live(public))
    target = proposal(session.current)
    target["answers"][1]["selected_options"] = ["2"]
    target["answers"][2]["selected_options"] = ["3"]
    expected = recovery_target(session.current)
    expected["answers"] = deepcopy(target["answers"])
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, target)
    session.after = None
    session.posts.clear()
    if mismatch == "answers":
        expected["answers"][2]["selected_options"] = ["4"]
    elif mismatch in {"race_id", "gameday_id", "season"}:
        expected[mismatch] += 1
    else:
        expected[mismatch] = "different-target"
    monkeypatch.setattr(
        account,
        "_snapshot",
        lambda *a, **k: pytest.fail(
            "mismatched journal must be rejected before readback"
        ),
    )
    with pytest.raises(
        account.AccountError, match="differs from expected recovery target"
    ):
        account.recover(tmp_path, 2026, expected=expected)
    assert session.posts == []


def test_expected_recovery_resumes_only_matching_target_and_confirms_verified_journal(
    monkeypatch, tmp_path, public
):
    session, _ = install(monkeypatch, tmp_path, live(public))
    target = proposal(session.current)
    target["answers"][1]["selected_options"] = ["2"]
    target["answers"][2]["selected_options"] = ["3"]
    expected = recovery_target(session.current)
    expected["answers"] = deepcopy(target["answers"])
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, target)
    session.after = None
    assert (
        account.recover(tmp_path, 2026, expected=expected)["apply_status"] == "verified"
    )
    assert len(session.posts) == 2
    session.current.update(locked=True, deadline_utc=None, deadline_authority=None)
    assert (
        account.recover(tmp_path, 2026, expected=expected)["apply_status"] == "verified"
    )
    assert len(session.posts) == 2
    assert account.recover(tmp_path, 2026)["apply_status"] == "nothing_to_recover"


@pytest.fixture
def public():
    return {
        "season": 2026,
        "gameday_id": 19,
        "race_id": 7403,
        "scope": "round",
        "deadline_utc": "2099-10-31T21:00:00+00:00",
        "deadline_authority": account.AUTHORITY,
        "first_session_utc": "2099-10-31T21:00:00+00:00",
        "locked": False,
        "fetched_at": "2026-10-29T00:00:00+00:00",
        "roster": [],
        "questions": [
            {
                "id": 694 + i,
                "number": i + 1,
                "text": f"Question {i + 1}",
                "template": 1 if i == 0 else 4,
                "choice_limit": 3 if i == 0 else 1,
                "status": 2,
                "config": {},
                "options": [
                    {
                        "id": str(j),
                        "name": str(j),
                        "points": float(j * 5),
                        "kind": 1,
                        "tla": "",
                        "team_id": "",
                    }
                    for j in range(1, 5)
                ],
            }
            for i in range(10)
        ],
    }


def fingerprint(snapshot):
    return account._digest(
        {
            k: snapshot[k]
            for k in ("season", "gameday_id", "race_id", "scope", "questions")
        }
    )


@pytest.fixture(autouse=True)
def api(monkeypatch):
    monkeypatch.setattr(
        account,
        "_api",
        lambda: SimpleNamespace(
            fingerprint=fingerprint, validate_answers=lambda snapshot, answers: None
        ),
    )


def choices(public, *, empty=False):
    return [
        {
            "question_id": q["id"],
            "selected_options": []
            if empty
            else (["1", "2", "3"] if q["template"] == 1 else ["1"]),
            "booster_id": "0",
        }
        for q in public["questions"]
    ]


def live(public, answers=None):
    result = deepcopy(public)
    result.update(
        answers=deepcopy(answers if answers is not None else choices(public)),
        question_fingerprint=fingerprint(public),
        binding_fingerprint="fixture-binding",
    )
    return result


def proposal(snapshot):
    return {
        **{
            k: snapshot[k]
            for k in (
                "season",
                "gameday_id",
                "race_id",
                "scope",
                "question_fingerprint",
            )
        },
        "complete": True,
        "answers": deepcopy(snapshot["answers"]),
        "probabilities": "ignored metadata",
    }


class FakeSession:
    def __init__(self, current):
        self.current = deepcopy(current)
        self.posts = []
        self.error = None
        self.after = None
        self.observe_guid = "fixture-guid"

    def observe(self, gameday, timeout_seconds=30, manual=False):
        return {"guid": self.observe_guid, "gameday_id": gameday}

    def post(self, payload):
        self.posts.append(deepcopy(payload))
        for answer in payload["Predictions"]:
            row = next(
                r
                for r in self.current["answers"]
                if r["question_id"] == answer["QuestionId"]
            )
            row.update(
                selected_options=answer["SelectedOption"],
                booster_id=answer["BoosterId"],
            )
        if self.after:
            self.after(self)
        if self.error:
            raise self.error


def install(monkeypatch, tmp_path, current):
    root = account.storage_directory(tmp_path)
    account.security._private_directory(root)
    binding = {"service": "predict", "season": 2026, "guid": "fixture-guid"}
    account.security._atomic(root / "binding.json", binding)
    session = FakeSession(current)
    session.current["binding_fingerprint"] = account.binding_fingerprint(binding)

    @contextmanager
    def browser(_):
        yield session

    monkeypatch.setattr(account, "_browser", browser)
    monkeypatch.setattr(
        account, "_snapshot", lambda *args, **kwargs: deepcopy(session.current)
    )
    return session, root


def test_exact_single_question_request_and_no_blind_repeat(
    monkeypatch, tmp_path, public
):
    before = live(public)
    target = proposal(before)
    target["answers"][0]["selected_options"] = ["3", "2", "1"]
    session, root = install(monkeypatch, tmp_path, before)
    original = session.post

    def prepared(payload):
        assert account._journal(root)[-1]["steps"][0]["status"] == "prepared"
        original(payload)

    session.post = prepared
    assert account.apply(tmp_path, 2026, target)["apply_status"] == "verified"
    assert session.posts == [
        {
            "RaceId": 7403,
            "GameDayId": 19,
            "PlatformId": 1,
            "Predictions": [
                {"QuestionId": 694, "SelectedOption": ["3", "2", "1"], "BoosterId": "0"}
            ],
        }
    ]
    account.apply(tmp_path, 2026, target)
    assert len(session.posts) == 1
    assert (root / "journal.json").stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700
    assert "fixture-guid" not in json.dumps(account.audit(tmp_path))


def test_move_chip_clears_old_before_setting_new(monkeypatch, tmp_path, public):
    before = live(public)
    before["answers"][9]["booster_id"] = "1"
    target = proposal(before)
    target["answers"][9]["booster_id"] = "0"
    target["answers"][0]["booster_id"] = "1"
    session, _ = install(monkeypatch, tmp_path, before)
    account.apply(tmp_path, 2026, target)
    assert [p["Predictions"][0]["QuestionId"] for p in session.posts] == [703, 694]
    assert [p["Predictions"][0]["BoosterId"] for p in session.posts] == ["0", "1"]


@pytest.mark.parametrize("change", ["locked", "deadline", "authority"])
def test_missing_authority_or_lock_blocks_changes_but_not_noop(
    monkeypatch, tmp_path, public, change
):
    before = live(public)
    if change == "locked":
        before["locked"] = True
    elif change == "deadline":
        before["deadline_utc"] = None
    else:
        before["deadline_authority"] = "session-start-plus40"
    session, _ = install(monkeypatch, tmp_path, before)
    target = proposal(before)
    assert account.apply(tmp_path, 2026, target)["apply_status"] == "verified"
    target["answers"][1]["selected_options"] = ["2"]
    with pytest.raises(account.AccountError):
        account.apply(tmp_path, 2026, target)
    assert not session.posts


@pytest.mark.parametrize(
    "change",
    [
        "season",
        "race_id",
        "gameday_id",
        "scope",
        "question_fingerprint",
        "complete",
        "duplicate",
        "cardinality",
        "option",
        "boost",
        "two_boosts",
    ],
)
def test_malformed_or_stale_recommendations(public, change):
    snapshot = live(public)
    target = proposal(snapshot)
    if change == "complete":
        target[change] = False
    elif change == "duplicate":
        target["answers"][1] = target["answers"][0]
    elif change == "cardinality":
        target["answers"][0]["selected_options"] = ["1", "2"]
    elif change == "option":
        target["answers"][1]["selected_options"] = ["99"]
    elif change == "boost":
        target["answers"][1]["booster_id"] = 1
    elif change == "two_boosts":
        target["answers"][1]["booster_id"] = target["answers"][2]["booster_id"] = "1"
    else:
        target[change] = 0
    with pytest.raises(account.AccountError):
        account._recommendation(target, snapshot)


@pytest.mark.parametrize("damage", ["unaffected", "order", "boost"])
def test_readback_verifies_every_answer_and_order(
    monkeypatch, tmp_path, public, damage
):
    before = live(public)
    target = proposal(before)
    target["answers"][1]["selected_options"] = ["2"]
    session, _ = install(monkeypatch, tmp_path, before)

    def corrupt(s):
        if damage == "unaffected":
            s.current["answers"][8]["selected_options"] = ["4"]
        elif damage == "order":
            s.current["answers"][0]["selected_options"].reverse()
        else:
            s.current["answers"][0]["booster_id"] = "1"

    session.after = corrupt
    with pytest.raises(account.AccountError, match="readback mismatch"):
        account.apply(tmp_path, 2026, target)
    with pytest.raises(account.AccountError, match="no blind resend"):
        account.recover(tmp_path, 2026)
    assert len(session.posts) == 1
    assert account.audit(tmp_path)[0]["status"] == "unknown"


def test_timeout_readback_can_verify_without_resending(monkeypatch, tmp_path, public):
    before = live(public)
    target = proposal(before)
    target["answers"][1]["selected_options"] = ["2"]
    session, _ = install(monkeypatch, tmp_path, before)
    session.error = TimeoutError("private raw transport text")
    assert account.apply(tmp_path, 2026, target)["apply_status"] == "verified"
    assert len(session.posts) == 1


def test_crash_recovery_reconciles_prepared_then_resumes_only_ready(
    monkeypatch, tmp_path, public
):
    before = live(public)
    target = proposal(before)
    target["answers"][1]["selected_options"] = ["2"]
    target["answers"][2]["selected_options"] = ["3"]
    session, root = install(monkeypatch, tmp_path, before)
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, target)
    assert account._journal(root)[0]["steps"][0]["status"] == "prepared"
    session.after = None
    account.recover(tmp_path, 2026)
    assert [p["Predictions"][0]["QuestionId"] for p in session.posts] == [695, 696]


def test_restart_recovery_of_last_write_works_after_lock(monkeypatch, tmp_path, public):
    before = live(public)
    target = proposal(before)
    target["answers"][1]["selected_options"] = ["2"]
    session, _ = install(monkeypatch, tmp_path, before)
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, target)
    session.current.update(locked=True, deadline_utc=None, deadline_authority=None)
    session.after = None
    assert account.recover(tmp_path, 2026)["apply_status"] == "verified"
    assert len(session.posts) == 1


def test_ready_steps_reject_changed_points_or_window(monkeypatch, tmp_path, public):
    before = live(public)
    target = proposal(before)
    target["answers"][1]["selected_options"] = ["2"]
    target["answers"][2]["selected_options"] = ["3"]
    session, _ = install(monkeypatch, tmp_path, before)
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, target)
    session.after = None
    session.current["question_fingerprint"] = "changed-points"
    with pytest.raises(account.AccountError, match="points"):
        account.recover(tmp_path, 2026)
    assert len(session.posts) == 1


def test_repeat_noop_does_not_override_later_manual_answers(
    monkeypatch, tmp_path, public
):
    before = live(public)
    session, _ = install(monkeypatch, tmp_path, before)
    target = proposal(before)
    account.apply(tmp_path, 2026, target)
    session.current["answers"][1]["selected_options"] = ["2"]
    with pytest.raises(account.AccountError, match="will not overwrite"):
        account.apply(tmp_path, 2026, target)
    assert not session.posts


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"Meta": {"Success": False}, "Data": {"Value": {}}},
        {"Meta": {"Success": True}},
    ],
)
def test_expired_or_malformed_envelopes(body):
    with pytest.raises(account.AccountError):
        account._unwrap(body)


def test_partial_official_answers_are_not_fabricated_full_answers(public):
    rows = account._answers(
        {
            "Predictions": [
                {"QuestionId": 694, "SelectedOption": [1, "0", 3], "BoosterId": "0"}
            ]
        },
        public,
        "guid",
    )
    assert rows[0]["selected_options"] == ["1", "0", "3"]
    assert rows[1]["selected_options"] == []


def test_connect_binds_real_observation_in_separate_namespace(
    monkeypatch, tmp_path, public
):
    fantasy = tmp_path / "binding.json"
    fantasy.write_text('{"team_number":2}')
    session, root = install(monkeypatch, tmp_path, live(public))
    (root / "binding.json").unlink()
    monkeypatch.setattr(account, "_fetch", lambda *args, **kwargs: public)
    result = account.connect(tmp_path, 2026)
    assert "guid" not in result
    assert account._binding(root, 2026)["guid"] == session.observe_guid
    assert json.loads(fantasy.read_text()) == {"team_number": 2}


def test_observer_rejects_foreign_origin_and_expiry():
    session = object.__new__(account._Session)
    session.observations, session.failed = [], False
    body = {"Meta": {"Success": True}, "Data": {"Value": {"Predictions": []}}}
    response = SimpleNamespace(
        url="https://evil.example/services/user/gameplay/leak/19/prediction",
        status=200,
        json=lambda: body,
    )
    session._observe(response)
    assert not session.observations
    response.url = account.BASE + "/services/user/gameplay/guid/19/prediction"
    session._observe(response)
    assert session.observations == [{"guid": "guid", "gameday_id": 19}]
    response.status = 401
    session._observe(response)
    assert session.failed


def test_transport_uses_cookie_context_exact_header_no_retry():
    calls = []
    response = SimpleNamespace(
        status=200,
        json=lambda: {
            "Meta": {"Success": True},
            "Data": {"Value": {"Predictions": []}},
        },
    )
    request = SimpleNamespace(
        get=lambda *a, **k: calls.append((a, k)) or response,
        post=lambda *a, **k: calls.append((a, k)) or response,
    )
    session = object.__new__(account._Session)
    session.context = SimpleNamespace(request=request)
    session.get("/services/user/gameplay/guid/19/prediction")
    session.post({"Predictions": []})
    for args, kwargs in calls:
        assert args[0].startswith(account.BASE)
        assert kwargs["headers"]["entity"] == "d3@t4N0te!"
        assert kwargs["max_redirects"] == kwargs["max_retries"] == 0


def test_browser_routes_block_answer_and_terms_writes():
    results = []
    for method, path in [
        ("POST", account.SAVE),
        ("POST", "/services/user/session/usernameupdate"),
        ("POST", "/services/session/login"),
        ("GET", account.SAVE),
    ]:
        route = SimpleNamespace(
            request=SimpleNamespace(url=account.BASE + path, method=method),
            continue_=lambda: results.append("continue"),
            abort=lambda: results.append("abort"),
        )
        account._Session._route(route)
    assert results == ["abort", "abort", "continue", "continue"]


def test_snapshot_ignores_unverified_public_deadline(monkeypatch, public):
    monkeypatch.setattr(account, "_fetch", lambda *a, **kw: deepcopy(public))
    session = SimpleNamespace(
        observe=lambda *_: {"guid": "g", "gameday_id": 19},
        get=lambda _: {"Predictions": []},
        deadline=lambda _: None,
    )
    result = account._snapshot(
        session, {"guid": "g", "season": 2026, "service": "predict"}
    )
    assert result["deadline_utc"] is result["deadline_authority"] is None
    session.observe = lambda *_: {"guid": "different", "gameday_id": 19}
    with pytest.raises(account.AccountError, match="differs"):
        account._snapshot(session, {"guid": "g", "season": 2026, "service": "predict"})


def test_security_lock_symlink_and_integrity(monkeypatch, tmp_path, public):
    session, root = install(monkeypatch, tmp_path, live(public))
    with account.security._locked(root):
        with pytest.raises(account.security.AccountError, match="Another"):
            account.audit(tmp_path)
    account.apply(tmp_path, 2026, proposal(session.current))
    path = root / "journal.json"
    damaged = json.loads(path.read_text())
    damaged[0]["expected"] = []
    path.write_text(json.dumps(damaged))
    with pytest.raises(account.AccountError, match="integrity"):
        account.audit(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(other, target_is_directory=True)
    with pytest.raises(account.security.AccountError, match="symlinks"):
        account.audit(link)


def test_scheduler_can_shorten_but_not_replace_deadline(public, monkeypatch):
    snapshot = live(public)
    now = datetime(2099, 10, 31, 20, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(account, "_now", lambda: now)
    with account._safety_cutoff(now):
        with pytest.raises(account.AccountError, match="safety cutoff"):
            account._writable(snapshot)
    account._writable(snapshot)


def test_scheduled_precondition_is_rechecked_inside_account_lock(
    monkeypatch, tmp_path, public
):
    session, _ = install(monkeypatch, tmp_path, live(public))
    expected = deepcopy(session.current)
    target = proposal(expected)
    target["answers"][1]["selected_options"] = ["2"]
    session.current["answers"][8]["selected_options"] = ["4"]
    with account._safety_cutoff(
        account._timestamp(public["deadline_utc"]), expected=expected
    ):
        with pytest.raises(
            account.AccountError, match="scheduled precondition changed"
        ):
            account.apply(tmp_path, 2026, target)
    assert not session.posts


@pytest.mark.parametrize(
    "field,value", [("race_id", 7404), ("question_fingerprint", "changed-points")]
)
def test_post_write_context_changes_are_uncertain(
    monkeypatch, tmp_path, public, field, value
):
    session, _ = install(monkeypatch, tmp_path, live(public))
    target = proposal(session.current)
    target["answers"][1]["selected_options"] = ["2"]
    session.after = lambda s: s.current.update({field: value})
    with pytest.raises(account.AccountError, match="readback mismatch"):
        account.apply(tmp_path, 2026, target)
    assert account.audit(tmp_path)[0]["status"] == "unknown"
    assert len(session.posts) == 1


def test_recovery_can_reconcile_but_not_resume_after_safety_cutoff(
    monkeypatch, tmp_path, public
):
    session, root = install(monkeypatch, tmp_path, live(public))
    target = proposal(session.current)
    target["answers"][1]["selected_options"] = ["2"]
    target["answers"][2]["selected_options"] = ["3"]
    session.after = lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, target)
    session.after = None
    with account._safety_cutoff(account._now()):
        with pytest.raises(account.AccountError, match="safety cutoff"):
            account.recover(tmp_path, 2026)
    steps = account._journal(root)[0]["steps"]
    assert [s["status"] for s in steps] == ["verified", "ready"]
    assert len(session.posts) == 1


@pytest.mark.parametrize(
    "values",
    [
        [],
        ["2099-10-31T21:00:00+00:00"],
        ["2099-10-31T21:00:00"],
        ["2099-10-31T21:00:00Z", "2099-10-31T22:00:00Z"],
    ],
)
def test_only_explicit_event_bound_unique_timezone_deadline_qualifies(public, values):
    selectors = []
    session = object.__new__(account._Session)

    def locator(selector):
        selectors.append(selector)
        return SimpleNamespace(evaluate_all=lambda _: values)

    session.page = SimpleNamespace(
        url=account.BASE + "/en/gameplay/19", locator=locator
    )
    if len(values) > 1 or (values and "+" not in values[0]):
        with pytest.raises(account.AccountError):
            session.deadline(public)
    else:
        assert session.deadline(public) == (values[0] if values else None)
    assert 'data-gameday-id="19"' in selectors[0]
    assert 'data-race-id="7403"' in selectors[0]
    session.page.url = account.BASE + "/en/gameplay/25"
    assert session.deadline(public) is None
