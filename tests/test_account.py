"""Offline contracts only: these fixtures are not captured authenticated evidence."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from f1fantasy import account


@pytest.fixture
def catalog():
    return {
        str(i): {
            "kind": "DRIVER" if i < 11 else "CONSTRUCTOR",
            "price": 100,
            "skill": 1 if i < 11 else 2,
        }
        for i in range(1, 14)
    }


@pytest.fixture
def fixture():
    return {
        "Season": "2026",
        "GamedayId": 19,
        "PhaseId": 1,
        "GDIsCurrent": 1,
        "MDIsCurrent": 1,
        "IsPostponed": 0,
        "GDIsLocked": 0,
        "MDIsLocked": 0,
        "MHIsLocked": 0,
        "SessionStartDateISO8601": "2026-10-31T21:00:00+00:00",
        "NextMatchDeadline": "0",
    }


@pytest.fixture
def raw():
    result = {
        "teamno": 2,
        "teamname": "do not expose account name",
        "playerid": [
            {"id": id_, "playerpostion": i + 1}
            for i, id_ in enumerate([1, 2, 3, 4, 5, 11, 12])
        ],
        "capplayerid": 1,
        "mgcapplayerid": 0,
        "gd_initial_team": [1, 2, 3, 4, 5, 11, 12],
        "team_info": {
            "teamBal": 30,
            "maxTeambal": 100,
            "subsallowed": 2,
            "userSubsleft": 2,
        },
        "isaccounting": 1,
        "islateonboard": 0,
        "boosterid": 0,
        "matchday": 43,
    }
    for flag, day in account.CHIP_FIELDS.values():
        result[flag] = 0
        result[day] = 0
    return result


@pytest.fixture
def history():
    return [{"teamno": 2, "mddetails": {"19": {"mds": 0}}}]


@pytest.fixture
def state(raw, fixture, catalog, history):
    return account._normalize(
        raw, fixture, catalog, history, (account._now() + timedelta(days=1)).isoformat()
    )


@pytest.fixture
def proposal(state):
    return {
        "season": 2026,
        "gameday_id": 19,
        "drivers": ["1", "2", "3", "4", "6"],
        "constructors": ["11", "12"],
        "boost_driver_id": "2",
        "chip": None,
        "x3_driver_id": None,
        "budget_tenths_m": 1000,
        "baseline_ids": state["baseline_ids"],
        "expected_transfer_penalty": 0,
    }


def envelope(value):
    return {"Meta": {"Success": True}, "Data": {"Value": value}}


class FakeSession:
    def __init__(self):
        self.posts = []
        self.post_error = False
        self.lock_checks = []
        self.lock_error = None

    def check_lock(self, season, gameday, phase):
        self.lock_checks.append((season, gameday, phase))
        if self.lock_error:
            raise self.lock_error

    def post(self, path, payload):
        self.posts.append((path, payload))
        if self.post_error:
            raise account.AccountError("unknown outcome")


def install(monkeypatch, directory, states, catalog):
    account._private_directory(directory)
    account._atomic(
        directory / "binding.json",
        {"guid": "account-identity", "season": 2026, "team_number": 2},
    )
    session = FakeSession()
    session.reads = 0

    @contextmanager
    def browser(_directory):
        yield session

    def snapshot(_session, _binding, observation=None):
        state = states[min(session.reads, len(states) - 1)]
        session.reads += 1
        if isinstance(state, Exception):
            raise state
        return deepcopy(state), deepcopy(catalog)

    monkeypatch.setattr(account, "_browser", browser)
    monkeypatch.setattr(account, "_snapshot", snapshot)
    return session


def after_state(state, catalog, proposal):
    _, _, expected = account._plan(state, catalog, account._proposal(proposal), True)
    return dict(state, **expected)


def test_recover_activated_chip_without_new_proposal(
    tmp_path, monkeypatch, state, catalog, proposal
):
    proposal.update(
        drivers=state["drivers"],
        boost_driver_id=state["boost_driver_id"],
        chip="x3",
        x3_driver_id="2",
    )
    after = after_state(state, catalog, proposal)
    # Simulate successful server activation followed by failed immediate read-back.
    session = install(
        monkeypatch,
        tmp_path,
        [state, account.AccountError("read failed"), after],
        catalog,
    )
    with pytest.raises(account.AccountError, match="unverified"):
        account.apply(tmp_path, 2026, proposal)
    recovered = account.recover(tmp_path, 2026)
    assert recovered["active_chip"] == "x3"
    assert recovered["apply_status"] == "verified"
    assert len(session.posts) == 1
    assert account.audit(tmp_path)[0]["status"] == "verified"


@pytest.mark.parametrize("chip", account.CHIPS)
@pytest.mark.parametrize("as_string", [False, True])
@pytest.mark.parametrize("day", [18, 19])
def test_chip_usage_accepts_own_identity_without_losing_activation_history(
    raw, fixture, catalog, history, chip, as_string, day
):
    flag, activation_day = account.CHIP_FIELDS[chip]
    raw[flag] = str(account.CHIPS[chip]) if as_string else account.CHIPS[chip]
    raw[activation_day] = day
    raw["boosterid"] = account.CHIPS[chip] if day == 19 else 0
    raw["mgcapplayerid"] = 2 if chip == "x3" else 0
    result = account._normalize(raw, fixture, catalog, history, None)
    assert chip not in result["available_chips"]
    assert result["active_chip"] == (chip if day == 19 else None)
    assert result["x3_driver_id"] == ("2" if chip == "x3" and day == 19 else None)


@pytest.mark.parametrize("usage", [2, 3, 4, 5, 7, "7", 6.0])
def test_chip_usage_rejects_other_identities_and_nonintegral_types(
    raw, fixture, catalog, history, usage
):
    raw["isextradrstaken"] = usage
    raw["extradrstakengd"] = 19
    raw["boosterid"] = 6
    raw["mgcapplayerid"] = 2
    with pytest.raises(account.AccountError, match="isextradrstaken"):
        account._normalize(raw, fixture, catalog, history, None)


def test_recover_conflicting_unknown_blocks_without_post(
    tmp_path, monkeypatch, state, catalog, proposal
):
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(account.AccountError, match="unverified"):
        account.apply(tmp_path, 2026, proposal)
    with pytest.raises(account.AccountError, match="no replay"):
        account.recover(tmp_path, 2026)
    assert len(session.posts) == 1


def test_normalized_budget_is_cap_not_unspent_balance(state):
    assert state["budget"] == 100
    assert state["remaining_budget_tenths_m"] == 300
    assert state["drivers"] == ["1", "2", "3", "4", "5"]
    assert state["baseline_ids"] == ["1", "2", "3", "4", "5", "11", "12"]
    assert state["carry"] == 0
    assert state["active_chip"] is None
    assert "final_fix" not in state["eligible_chips"]
    assert "teamname" not in state and "guid" not in state


@pytest.mark.parametrize("matchday", [1, 43])
def test_history_status_uses_current_fantasy_gameday(
    raw, fixture, catalog, history, matchday
):
    raw["matchday"] = matchday
    history[0]["mddetails"][str(matchday)] = {"mds": 3}
    result = account._normalize(raw, fixture, catalog, history, None)
    assert "x3" in result["eligible_chips"]


@pytest.mark.parametrize("details", [None, [], {"1": {"mds": 0}}])
def test_current_gameday_history_must_be_present(
    raw, fixture, catalog, history, details
):
    history[0]["mddetails"] = details
    with pytest.raises(account.AccountError, match="game.day history|current game day"):
        account._normalize(raw, fixture, catalog, history, None)


@pytest.mark.parametrize("empty_booster", [None, ""])
def test_empty_booster_when_chip_history_confirms_none_active(
    raw, fixture, catalog, history, empty_booster
):
    raw["boosterid"] = empty_booster
    # A previously used chip does not imply an active chip this weekend.
    raw.update(isautopilottaken=1, autopilottakengd=18)
    result = account._normalize(raw, fixture, catalog, history, None)
    assert result["active_chip"] is None
    assert "autopilot" not in result["available_chips"]


@pytest.mark.parametrize("empty_booster", [None, ""])
def test_active_chip_rejects_empty_booster(
    raw, fixture, catalog, history, empty_booster
):
    raw.update(boosterid=empty_booster, isautopilottaken=1, autopilottakengd=19)
    with pytest.raises(account.AccountError, match="Unverified active booster"):
        account._normalize(raw, fixture, catalog, history, None)


@pytest.mark.parametrize("chip", account.CHIP_FIELDS)
@pytest.mark.parametrize("empty_day", [None, ""])
def test_unused_chip_accepts_empty_activation_day(
    raw, fixture, catalog, history, chip, empty_day
):
    _, day = account.CHIP_FIELDS[chip]
    raw[day] = empty_day
    result = account._normalize(raw, fixture, catalog, history, None)
    assert chip in result["available_chips"]
    assert result["active_chip"] is None


@pytest.mark.parametrize("chip", account.CHIP_FIELDS)
@pytest.mark.parametrize("empty_day", [None, ""])
def test_used_chip_requires_activation_day(
    raw, fixture, catalog, history, chip, empty_day
):
    flag, day = account.CHIP_FIELDS[chip]
    raw.update({flag: 1, day: empty_day})
    with pytest.raises(account.AccountError, match=f"Unverified {day}"):
        account._normalize(raw, fixture, catalog, history, None)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.pop("gd_initial_team"),
        lambda raw: raw.update(gd_initial_team="1234567"),
        lambda raw: raw["playerid"].append({"id": 6, "playerpostion": 8}),
        lambda raw: raw["playerid"][0].update(playerpostion=2),
        lambda raw: raw["playerid"][0].update(id=True),
        lambda raw: raw["team_info"].update(teamBal="NaN"),
        lambda raw: raw["team_info"].update(teamBal=31),
        lambda raw: raw["team_info"].update(userSubsleft=1),
        lambda raw: raw.update(isautopilottaken=4),
        lambda raw: raw.update(boosterid=6),
    ],
)
def test_malformed_or_unreconciled_state_fails_closed(
    raw, fixture, catalog, history, mutation
):
    mutation(raw)
    with pytest.raises(account.AccountError):
        account._normalize(raw, fixture, catalog, history, None)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"Meta": {"Success": False}, "Data": {"Value": {}}},
        {"Meta": {"Success": "true"}, "Data": {"Value": {}}},
        {"Meta": {"Success": True}, "Data": {}},
    ],
)
def test_auth_expiry_and_unknown_envelopes_are_not_success(body):
    with pytest.raises(account.AccountError):
        account._unwrap(body)


def test_net_transfers_use_initial_baseline_not_latest_edit(
    raw, fixture, catalog, history
):
    raw["playerid"][-3]["id"] = 6
    raw["team_info"]["userSubsleft"] = 1
    state = account._normalize(raw, fixture, catalog, history, None)
    # Reverting back to driver 5 consumes zero net transfers, not another transfer.
    proposal = {
        "season": 2026,
        "gameday_id": 19,
        "drivers": ["1", "2", "3", "4", "5"],
        "constructors": ["11", "12"],
        "boost_driver_id": "1",
        "chip": None,
        "x3_driver_id": None,
        "budget_tenths_m": 1000,
        "baseline_ids": state["baseline_ids"],
        "expected_transfer_penalty": 0,
    }
    _, _, expected = account._plan(state, catalog, account._proposal(proposal), False)
    assert expected["net_transfers"] == 0
    assert expected["transfers_left"] == 2
    assert expected["transfer_penalty"] == 0


def test_exact_transfer_and_boost_payloads(state, catalog, proposal):
    path, body, _ = account._plan(state, catalog, account._proposal(proposal), False)
    assert path == "/services/user/gameplay/transferteam"
    assert account._numeric_payload(body) == {
        "platformId": 1,
        "platformVersion": "1",
        "platformCategory": "web",
        "gamedayId": 19,
        "phaseId": 1,
        "captainPlayerid": 2,
        "teamNumber": 2,
        "isWildCard": 0,
        "playerId": [1, 2, 3, 4, 6, 11, 12],
        "playerPosition": list(range(1, 8)),
        "playerSkill": [1, 1, 1, 1, 1, 2, 2],
    }
    proposal["drivers"] = state["drivers"]
    path, body, _ = account._plan(state, catalog, account._proposal(proposal), False)
    assert path.endswith("/captainupdate")
    assert account._numeric_payload(body) == {
        "platformId": 1,
        "platformVersion": "1",
        "platformCategory": "web",
        "gamedayId": 19,
        "phaseId": 1,
        "captainPlayerid": 2,
        "teamNumber": 2,
        "isWildCard": 0,
        "optType": 1,
    }


@pytest.mark.parametrize(
    "chip,endpoint",
    [
        ("wildcard", "transferteam"),
        ("limitless", "applylimitless"),
        ("autopilot", "applydrsenabled"),
        ("no_negative", "applynonegative"),
        ("x3", "applymegadriver"),
    ],
)
def test_single_request_chip_contracts(state, catalog, proposal, chip, endpoint):
    proposal["chip"] = chip
    if chip in {"autopilot", "no_negative", "x3"}:
        proposal["drivers"] = state["drivers"]
        proposal["boost_driver_id"] = state["boost_driver_id"]
    if chip == "x3":
        proposal["x3_driver_id"] = "2"
    path, body, expected = account._plan(
        state, catalog, account._proposal(proposal), False
    )
    assert path.endswith("/" + endpoint)
    assert expected["active_chip"] == chip
    if chip == "wildcard":
        assert body["isWildCard"] == 1 and body["boosterId"] == 2
    elif chip == "limitless":
        assert body == dict(
            account.PLATFORM,
            teamNo=2,
            tourGameDayId=19,
            phaseId=1,
            boosterId=1,
            captainPlayerId="2",
            playerId=[1, 2, 3, 4, 6, 11, 12],
            position=list(range(1, 8)),
            skill=[1, 1, 1, 1, 1, 2, 2],
        )
        assert "playerPosition" not in body
    else:
        common = dict(
            account.PLATFORM,
            teamNo=2,
            tourGameDayId=19,
            phaseId=1,
            boosterId=account.CHIPS[chip],
        )
        if chip == "x3":
            common.update(captainPlayerId="1", mgCaptainPlayerId="2")
        assert body == common


@pytest.mark.parametrize("chip", ["autopilot", "no_negative", "x3"])
def test_mixed_non_atomic_chip_lineup_rejected(state, catalog, proposal, chip):
    proposal["chip"] = chip
    if chip == "x3":
        proposal["x3_driver_id"] = "3"
    with pytest.raises(account.AccountError, match="Non-atomic"):
        account._plan(state, catalog, account._proposal(proposal), False)


def test_final_fix_missing_authority_is_explicitly_blocked(state, catalog, proposal):
    proposal["chip"] = "final_fix"
    with pytest.raises(account.AccountError, match="Final Fix blocked"):
        account._plan(state, catalog, account._proposal(proposal), False)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gameday_id", 20),
        ("season", 2027),
        ("budget_tenths_m", 1001),
        ("baseline_ids", ["1", "2", "3", "4", "6", "11", "12"]),
        ("expected_transfer_penalty", 10),
    ],
)
def test_event_budget_baseline_and_penalty_conflicts(
    state, catalog, proposal, field, value
):
    proposal[field] = value
    with pytest.raises(account.AccountError):
        account._plan(state, catalog, account._proposal(proposal), False)


def test_paid_transfers_need_explicit_permission(state, catalog, proposal):
    proposal.update(drivers=["1", "2", "6", "7", "8"], expected_transfer_penalty=10)
    with pytest.raises(account.AccountError, match="allow_penalties"):
        account._plan(state, catalog, account._proposal(proposal), False)
    _, _, expected = account._plan(state, catalog, account._proposal(proposal), True)
    assert expected["net_transfers"] == 3
    assert expected["transfers_left"] == -1


def test_prepare_precedes_mutation_and_repeat_reads_without_reposting(
    tmp_path, monkeypatch, state, catalog, proposal
):
    after = after_state(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, after, after], catalog)
    original = session.post

    def post(path, body):
        journal = json.loads((tmp_path / "journal.json").read_text())
        assert journal[0]["status"] == "prepared"
        assert (tmp_path / "journal.json").stat().st_mode & 0o777 == 0o600
        original(path, body)

    session.post = post
    first = account.apply(tmp_path, 2026, proposal)
    proposal["drivers"].reverse()
    second = account.apply(tmp_path, 2026, proposal)
    assert first["apply_status"] == second["apply_status"] == "verified"
    assert first["idempotency_key"] == second["idempotency_key"]
    assert len(session.posts) == 1 and session.reads == 3
    assert account.audit(tmp_path)[0]["status"] == "verified"
    assert "guid" not in (tmp_path / "journal.json").read_text()
    assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_timeout_is_read_back_before_considering_success(
    tmp_path, monkeypatch, state, catalog, proposal
):
    after = after_state(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, after], catalog)
    session.post_error = True
    assert account.apply(tmp_path, 2026, proposal)["apply_status"] == "verified"
    assert len(session.posts) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("boost_driver_id", "1"),
        ("drivers", ["1", "2", "3", "4", "5"]),
        ("remaining_budget_tenths_m", 301),
        ("transfers_left", 2),
        ("active_chip", "wildcard"),
        ("x3_driver_id", "3"),
    ],
)
def test_readback_mismatch_is_durable_and_never_retried(
    tmp_path, monkeypatch, state, catalog, proposal, field, value
):
    after = after_state(state, catalog, proposal)
    after[field] = value
    session = install(monkeypatch, tmp_path, [state, after], catalog)
    with pytest.raises(account.AccountError, match="read-back unverified"):
        account.apply(tmp_path, 2026, proposal)
    assert account.audit(tmp_path)[0]["status"] == "unknown"
    with pytest.raises(account.AccountError, match="no replay"):
        account.apply(tmp_path, 2026, proposal)
    assert len(session.posts) == 1


def test_restart_after_prepare_recovers_even_after_deadline(
    tmp_path, monkeypatch, state, catalog, proposal
):
    after = after_state(state, catalog, proposal)
    after.update(locked=True, lock_deadline_utc=None)
    session = install(monkeypatch, tmp_path, [state], catalog)

    def interrupted(_path, _body):
        raise KeyboardInterrupt

    session.post = interrupted
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, proposal)
    assert account.audit(tmp_path)[0]["status"] == "prepared"
    # New process/session: only durable journal + current server state survive.
    recovered = install(monkeypatch, tmp_path, [after], catalog)
    assert account.apply(tmp_path, 2026, proposal)["apply_status"] == "verified"
    assert recovered.posts == []


def test_unknown_prior_outcome_blocks_different_proposal(
    tmp_path, monkeypatch, state, catalog, proposal
):
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(account.AccountError):
        account.apply(tmp_path, 2026, proposal)
    proposal["boost_driver_id"] = "3"
    with pytest.raises(account.AccountError, match="Previous apply outcome"):
        account.apply(tmp_path, 2026, proposal)
    assert len(session.posts) == 1


@pytest.mark.parametrize(
    "deadline,locked",
    [("2000-01-01T00:00:00Z", False), (None, True), ("2099-01-01T00:00:00Z", True)],
)
def test_expired_deadline_or_locked_state_never_posts(
    tmp_path, monkeypatch, state, catalog, proposal, deadline, locked
):
    state.update(lock_deadline_utc=deadline, locked=locked)
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(account.AccountError, match="deadline|locked"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == []
    assert account.audit(tmp_path) == []


def test_live_unlocked_status_allows_save_without_timestamp(
    tmp_path, monkeypatch, state, catalog, proposal
):
    state["lock_deadline_utc"] = None
    after = after_state(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, after], catalog)
    assert account.apply(tmp_path, 2026, proposal)["apply_status"] == "verified"
    assert session.lock_checks == [(2026, 19, 1)]
    assert len(session.posts) == 1


def test_lock_changed_since_snapshot_never_prepares_or_posts(
    tmp_path, monkeypatch, state, catalog, proposal
):
    session = install(monkeypatch, tmp_path, [state], catalog)
    session.lock_error = account.AccountError(
        "Fantasy team is locked by the current server session"
    )
    with pytest.raises(account.AccountError, match="locked"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == []
    assert account.audit(tmp_path) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("GDIsLocked", 1),
        ("MDIsLocked", 1),
        ("MHIsLocked", 1),
        ("GDIsLocked", None),
        ("MDIsCurrent", 0),
        ("GamedayId", 20),
        ("PhaseId", 2),
        ("IsPostponed", 1),
    ],
)
def test_fresh_lock_check_rejects_locked_unknown_or_changed_session(
    fixture, field, value
):
    fixture[field] = value
    session = account._Session.__new__(account._Session)
    session.get = lambda path: {"Data": {"fixtures": [fixture]}}
    with pytest.raises(account.AccountError):
        session.check_lock(2026, 19, 1)


def test_fresh_lock_check_uses_current_official_flags_not_session_time(fixture):
    fixture["SessionStartDateISO8601"] = "2000-01-01T00:00:00Z"
    session = account._Session.__new__(account._Session)
    calls = []
    session.get = lambda path: calls.append(path) or {"Data": {"fixtures": [fixture]}}
    session.check_lock(2026, 19, 1)
    assert calls == ["/feeds/v2/schedule/raceday_en.json"]


@pytest.mark.parametrize("status", [1, 2, 3])
def test_started_team_session_blocks_ordinary_changes(
    raw, fixture, catalog, history, status
):
    history[0]["mddetails"]["19"]["mds"] = status
    normalized = account._normalize(raw, fixture, catalog, history, None)
    assert normalized["locked"] is True
    assert normalized["eligible_chips"] == []


def test_auth_expiry_before_write_cannot_prepare(
    tmp_path, monkeypatch, catalog, proposal
):
    session = install(
        monkeypatch, tmp_path, [account.AccountError("Authentication expired")], catalog
    )
    with pytest.raises(account.AccountError, match="Authentication expired"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == [] and account.audit(tmp_path) == []


def test_selected_snapshot_rechecks_observed_identity(monkeypatch):
    binding = {"guid": "bound", "season": 2026, "team_number": 2}
    session = SimpleNamespace(observe=lambda _timeout: {"guid": "other"})
    with pytest.raises(account.AccountError, match="bound identity"):
        account._snapshot(session, binding)


def test_connect_requires_real_observation_and_selected_team(
    tmp_path, monkeypatch, state, catalog, raw, fixture, history
):
    session = FakeSession()
    session.observe = lambda _timeout, **kwargs: {
        "guid": "observed-account",
        "value": {"userTeam": []},
        "gameday_id": 19,
        "phase_id": 1,
    }
    session.get = lambda path: envelope(
        history if "getusergamedaysv1" in path else {"userTeam": [raw]}
    )
    session.deadline = lambda: None

    @contextmanager
    def browser(_directory):
        yield session

    monkeypatch.setattr(account, "_browser", browser)
    monkeypatch.setattr(account, "_public", lambda *args: (fixture, catalog))
    result = account.connect(tmp_path, 2026, 2)
    assert result["team_number"] == 2
    assert (
        json.loads((tmp_path / "binding.json").read_text())["guid"]
        == "observed-account"
    )
    assert (tmp_path / "binding.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(account.AccountError, match="selected team"):
        account.connect(tmp_path, 2026, 1)
    assert session.posts == []


def test_expired_connect_does_not_create_binding(tmp_path, monkeypatch):
    @contextmanager
    def browser(_directory):
        def observe(_timeout, **kwargs):
            raise account.AccountError("No authenticated official getteam response")

        yield SimpleNamespace(observe=observe)

    monkeypatch.setattr(account, "_browser", browser)
    with pytest.raises(account.AccountError, match="No authenticated"):
        account.connect(tmp_path, 2026, 1, 1)
    assert not (tmp_path / "binding.json").exists()


def test_journal_corruption_blocks_new_writes(
    tmp_path, monkeypatch, state, catalog, proposal
):
    after = after_state(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, after], catalog)
    account.apply(tmp_path, 2026, proposal)
    path = tmp_path / "journal.json"
    journal = json.loads(path.read_text())
    journal[0]["expected"] = {}
    path.write_text(json.dumps(journal))
    with pytest.raises(account.AccountError, match="integrity"):
        account.apply(tmp_path, 2026, proposal)
    assert len(session.posts) == 1


def test_noop_is_journaled_and_does_not_override_later_manual_edit(
    tmp_path, monkeypatch, state, catalog, proposal
):
    proposal.update(drivers=state["drivers"], boost_driver_id=state["boost_driver_id"])
    changed = dict(state, boost_driver_id="3")
    session = install(monkeypatch, tmp_path, [state, changed], catalog)
    assert account.apply(tmp_path, 2026, proposal)["apply_status"] == "unchanged"
    with pytest.raises(account.AccountError, match="Previous apply outcome"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == []


def test_lock_and_symlink_protection(tmp_path):
    directory = tmp_path / "account"
    with account._locked(directory):
        with pytest.raises(account.AccountError, match="Another account operation"):
            account.audit(directory)
    link = tmp_path / "link"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(account.AccountError, match="symlinks"):
        account.audit(link)
    (directory / "operation.lock").unlink()
    (directory / "operation.lock").symlink_to(tmp_path / "outside")
    with pytest.raises(account.AccountError, match="private account lock"):
        account.audit(directory)
    assert not (tmp_path / "outside").exists()


def test_browser_observer_ignores_other_origins_and_rejects_auth_errors():
    session = account._Session.__new__(account._Session)
    session.observations = []
    session.auth_failure = False
    response = SimpleNamespace(
        url="https://evil.example/services/user/gameplay/user/getteam/1/2/19/1",
        status=200,
        json=lambda: envelope({"userTeam": []}),
    )
    session._observe(response)
    assert session.observations == []
    response.url = account.BASE + "/services/user/gameplay/observed/getteam/1/2/19/1"
    session._observe(response)
    assert session.observations[0]["guid"] == "observed"
    response.status = 401
    session._observe(response)
    assert session.auth_failure


def test_request_cookies_context_and_no_retry_or_redirect():
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status=200, json=lambda: envelope({}))

    session = account._Session.__new__(account._Session)
    session.context = SimpleNamespace(request=SimpleNamespace(post=post))
    session.post(account.TEAM + "captainupdate", {"teamNumber": 2})
    assert calls == [
        (
            account.BASE + account.TEAM + "captainupdate",
            {
                "data": {"teamNumber": 2},
                "timeout": 20000,
                "max_redirects": 0,
                "max_retries": 0,
            },
        )
    ]


def test_public_refresh_checks_statistics_prices_and_event(
    monkeypatch, fixture, catalog
):
    calls = []
    assets = tuple(
        SimpleNamespace(id=id_, kind=row["kind"], price=row["price"])
        for id_, row in catalog.items()
    )
    monkeypatch.setattr(
        account.data, "load_assets", lambda gd: (assets, account._now())
    )
    monkeypatch.setattr(
        account.data,
        "load_statistics",
        lambda season, assets: calls.append("stats") or object(),
    )
    rows = [
        {
            "PlayerId": int(id_),
            "PositionName": row["kind"],
            "Value": row["price"] / 10,
            "Skill": row["skill"],
            "IsActive": 1,
        }
        for id_, row in catalog.items()
    ]

    def get(path):
        calls.append(path)
        return (
            {"Data": {"fixtures": [fixture]}}
            if "schedule" in path
            else {"Data": {"Value": rows}}
        )

    session = SimpleNamespace(get=get)
    assert account._public(session, 2026, 19, 1)[1] == catalog
    assert "stats" in calls
    rows[0]["Value"] = 11
    with pytest.raises(account.AccountError, match="prices changed"):
        account._public(session, 2026, 19, 1)
    with pytest.raises(account.AccountError, match="unique current"):
        account._public(session, 2026, 20, 1)


def test_deadline_never_derived_from_session_countdown():
    session = account._Session.__new__(account._Session)
    session.page = SimpleNamespace(
        locator=lambda _selector: SimpleNamespace(evaluate_all=lambda _js: [])
    )
    assert session.deadline() is None
    with pytest.raises(account.AccountError, match="timestamp"):
        account._timestamp("2026-10-31T21:00:00")


def test_missing_optional_dependency_error_is_actionable(tmp_path, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(account.AccountError, match="optional account dependency"):
        with account._browser(tmp_path):
            pytest.fail("browser should not launch")


@pytest.mark.parametrize(
    "override,installed,expected",
    [
        (None, {"chromium": "/usr/bin/chromium"}, "/usr/bin/chromium"),
        (
            None,
            {"chromium-browser": "/usr/bin/chromium-browser"},
            "/usr/bin/chromium-browser",
        ),
        ("/custom/chromium", {"chromium": "/usr/bin/chromium"}, "/custom/chromium"),
        (None, {}, None),
    ],
)
def test_browser_uses_system_chromium_or_explicit_override(
    tmp_path, monkeypatch, override, installed, expected
):
    import sys

    if override:
        monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_PATH", override)
    else:
        monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_PATH", raising=False)
    monkeypatch.setattr(account.shutil, "which", installed.get)
    calls = []
    context = SimpleNamespace(close=lambda: calls.append("closed"))

    def launch(profile, **options):
        calls.append((profile, options))
        return context

    @contextmanager
    def playwright():
        yield SimpleNamespace(
            chromium=SimpleNamespace(launch_persistent_context=launch)
        )

    monkeypatch.setitem(
        sys.modules, "playwright.sync_api", SimpleNamespace(sync_playwright=playwright)
    )
    monkeypatch.setattr(account, "_Session", lambda value: value)
    with account._browser(tmp_path) as session:
        assert session is context
        assert calls[0][0] == str(tmp_path / "browser")
        assert calls[0][1]["headless"] is False
        assert calls[0][1].get("executable_path") == expected
    assert calls[-1] == "closed"


@pytest.mark.parametrize("day", [0, "0"])
def test_used_chip_requires_positive_activation_day(
    raw, fixture, catalog, history, day
):
    raw.update(isextradrstaken=6, extradrstakengd=day)
    with pytest.raises(account.AccountError, match="extradrstakengd"):
        account._normalize(raw, fixture, catalog, history, None)
