"""Combined saves verify transfers before spending a chip and survive restarts."""

from copy import deepcopy

import pytest

from f1fantasy import account
from test_account import (
    catalog,
    fixture,
    history,
    proposal,
    raw,
    state,
    install,
    after_state,
)


def stages(state, catalog, proposal, chip="x3"):
    proposal.update(chip=chip, x3_driver_id="6" if chip == "x3" else None)
    lineup = dict(proposal, chip=None, x3_driver_id=None)
    middle = after_state(state, catalog, lineup)
    final = after_state(middle, catalog, proposal)
    return middle, final


@pytest.mark.parametrize(
    "chip,endpoint",
    [
        ("autopilot", "applydrsenabled"),
        ("no_negative", "applynonegative"),
        ("x3", "applymegadriver"),
    ],
)
def test_combined_save_verifies_lineup_before_activating_chip(
    tmp_path, monkeypatch, state, catalog, proposal, chip, endpoint
):
    middle, final = stages(state, catalog, proposal, chip)
    session = install(monkeypatch, tmp_path, [state, middle, final, final], catalog)
    post = session.post

    def inspect(path, payload):
        row = account._ledger(tmp_path)[0]
        index = len(session.posts)
        assert row["steps"][index]["status"] == "prepared"
        if index:
            assert row["steps"][0]["status"] == "verified"
            assert session.reads == 2
        post(path, payload)

    session.post = inspect
    result = account.apply(tmp_path, 2026, proposal)
    assert result["apply_status"] == "verified"
    assert result["active_chip"] == chip
    assert result["drivers"] == final["drivers"]
    assert [path.rsplit("/", 1)[-1] for path, _ in session.posts] == [
        "transferteam",
        endpoint,
    ]
    assert session.posts[0][1].get("boosterId") is None
    assert len(session.lock_checks) == 2
    if chip == "x3":
        assert session.posts[1][1]["mgCaptainPlayerId"] == 6
        assert session.posts[1][1]["captainPlayerId"] == 2
    assert (
        account.apply(tmp_path, 2026, proposal)["idempotency_key"]
        == result["idempotency_key"]
    )
    assert len(session.posts) == 2
    assert [step["status"] for step in account.audit(tmp_path)[0]["steps"]] == [
        "verified",
        "verified",
    ]
    assert "proposal" not in account.audit(tmp_path)[0]["steps"][0]


def test_activated_x3_identity_readback_recovers_without_another_post(
    tmp_path, monkeypatch, state, catalog, proposal, raw, fixture, history
):
    middle, _ = stages(state, catalog, proposal)
    session = install(
        monkeypatch,
        tmp_path,
        [state, middle, account.AccountError("Unknown isextradrstaken flag")],
        catalog,
    )
    with pytest.raises(account.AccountError, match="completed: transferteam"):
        account.apply(tmp_path, 2026, proposal)
    raw["playerid"] = [
        {"id": int(id_), "playerpostion": index + 1}
        for index, id_ in enumerate(proposal["drivers"] + proposal["constructors"])
    ]
    raw.update(
        capplayerid=2,
        mgcapplayerid=6,
        boosterid=6,
        isextradrstaken=6,
        extradrstakengd=19,
    )
    raw["team_info"]["userSubsleft"] = 1
    normalized = account._normalize(raw, fixture, catalog, history, None)
    assert account._matches(normalized, account._ledger(tmp_path)[0]["expected"])
    monkeypatch.setattr(account, "_snapshot", lambda *_args: (normalized, catalog))
    result = account.recover(tmp_path, 2026)
    assert result["active_chip"] == "x3"
    assert result["x3_driver_id"] == "6"
    assert len(session.posts) == 2
    assert account.audit(tmp_path)[0]["status"] == "verified"


@pytest.mark.parametrize("chip", ["autopilot", "no_negative"])
def test_boost_only_then_chip(tmp_path, monkeypatch, state, catalog, proposal, chip):
    proposal["drivers"] = state["drivers"]
    middle, final = stages(state, catalog, proposal, chip)
    session = install(monkeypatch, tmp_path, [state, middle, final], catalog)
    account.apply(tmp_path, 2026, proposal)
    assert session.posts[0][0].endswith("/captainupdate")
    assert len(session.posts) == 2


def test_first_step_mismatch_does_not_activate_or_replay_chip(
    tmp_path, monkeypatch, state, catalog, proposal
):
    stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(
        account.AccountError, match="none verified.*read-back unverified"
    ):
        account.apply(tmp_path, 2026, proposal)
    with pytest.raises(account.AccountError, match="no replay"):
        account.recover(tmp_path, 2026)
    assert len(session.posts) == 1
    assert account.audit(tmp_path)[0]["steps"][1]["status"] == "ready"


def test_late_first_readback_resumes_only_chip(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    first = install(
        monkeypatch, tmp_path, [state, account.AccountError("read failed")], catalog
    )
    with pytest.raises(account.AccountError, match="incomplete"):
        account.apply(tmp_path, 2026, proposal)
    recovered = install(monkeypatch, tmp_path, [middle, final], catalog)
    assert account.recover(tmp_path, 2026)["active_chip"] == "x3"
    assert len(first.posts) == len(recovered.posts) == 1
    assert recovered.posts[0][0].endswith("/applymegadriver")


def test_lock_between_steps_records_partial_and_resumes_unsent_chip(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, middle], catalog)
    check = session.check_lock

    def lock(season, gameday, phase):
        check(season, gameday, phase)
        if len(session.lock_checks) == 2:
            raise account.AccountError("locked")

    session.check_lock = lock
    with pytest.raises(account.AccountError, match="completed: transferteam.*locked"):
        account.apply(tmp_path, 2026, proposal)
    assert len(session.posts) == 1
    row = account.audit(tmp_path)[0]
    assert [step["status"] for step in row["steps"]] == ["verified", "ready"]
    recovered = install(monkeypatch, tmp_path, [middle, final], catalog)
    assert account.recover(tmp_path, 2026)["idempotency_key"] == row["key"]
    assert len(recovered.posts) == 1


def test_unknown_chip_activation_is_never_sent_again(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, middle, middle], catalog)
    with pytest.raises(
        account.AccountError, match="completed: transferteam.*unverified"
    ):
        account.apply(tmp_path, 2026, proposal)
    with pytest.raises(account.AccountError, match="no replay"):
        account.recover(tmp_path, 2026)
    assert len(session.posts) == 2
    recovered = install(monkeypatch, tmp_path, [dict(final, locked=True)], catalog)
    assert account.recover(tmp_path, 2026)["apply_status"] == "verified"
    assert recovered.posts == []


def test_timeout_at_each_step_uses_readback_without_reposting(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, middle, final], catalog)
    session.post_error = True
    assert account.apply(tmp_path, 2026, proposal)["apply_status"] == "verified"
    assert len(session.posts) == 2


@pytest.mark.parametrize("crash_step", [0, 1])
def test_crash_after_prepare_recovers_matching_step_without_replay(
    tmp_path, monkeypatch, state, catalog, proposal, crash_step
):
    middle, final = stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, middle], catalog)
    post = session.post

    def crash(path, payload):
        post(path, payload)
        if len(session.posts) == crash_step + 1:
            raise KeyboardInterrupt

    session.post = crash
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, proposal)
    recovered = install(
        monkeypatch, tmp_path, [middle, final] if crash_step == 0 else [final], catalog
    )
    assert account.recover(tmp_path, 2026)["apply_status"] == "verified"
    assert len(recovered.posts) == 1 - crash_step


def test_invalid_chip_is_rejected_before_saving_lineup(
    tmp_path, monkeypatch, state, catalog, proposal
):
    stages(state, catalog, proposal)
    state["eligible_chips"] = []
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(account.AccountError, match="eligible"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == []
    assert account.audit(tmp_path) == []


def test_external_change_between_steps_blocks_new_write(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, middle], catalog)
    check = session.check_lock

    def crash(season, gameday, phase):
        check(season, gameday, phase)
        if len(session.lock_checks) == 2:
            raise KeyboardInterrupt

    session.check_lock = crash
    with pytest.raises(KeyboardInterrupt):
        account.apply(tmp_path, 2026, proposal)
    changed = dict(middle, boost_driver_id="3")
    recovered = install(monkeypatch, tmp_path, [changed], catalog)
    with pytest.raises(account.AccountError, match="Account changed"):
        account.recover(tmp_path, 2026)
    assert recovered.posts == []


def test_resume_checks_fresh_prices_before_spending_chip(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    session = install(
        monkeypatch, tmp_path, [state, account.AccountError("read failed")], catalog
    )
    with pytest.raises(account.AccountError):
        account.apply(tmp_path, 2026, proposal)
    prices = deepcopy(catalog)
    prices["6"]["price"] += 1
    recovered = install(monkeypatch, tmp_path, [middle], prices)
    with pytest.raises(account.AccountError, match="prices or accounting changed"):
        account.recover(tmp_path, 2026)
    assert recovered.posts == []


def test_pending_apply_finishes_original_plan_instead_of_replacing_it(
    tmp_path, monkeypatch, state, catalog, proposal
):
    middle, final = stages(state, catalog, proposal)
    install(
        monkeypatch, tmp_path, [state, account.AccountError("read failed")], catalog
    )
    with pytest.raises(account.AccountError):
        account.apply(tmp_path, 2026, proposal)
    key = account.audit(tmp_path)[0]["key"]
    replacement = dict(proposal, boost_driver_id="3")
    recovered = install(monkeypatch, tmp_path, [middle, final], catalog)
    result = account.apply(tmp_path, 2026, replacement)
    assert result["idempotency_key"] == key
    assert result["boost_driver_id"] == "2"
    assert len(recovered.posts) == 1
    assert recovered.posts[0][1]["captainPlayerId"] == 2


def test_paid_combined_transfers_need_permission_before_either_step(
    tmp_path, monkeypatch, state, catalog, proposal
):
    proposal.update(
        drivers=["1", "2", "6", "7", "8"],
        chip="x3",
        x3_driver_id="6",
        expected_transfer_penalty=10,
    )
    lineup = dict(proposal, chip=None, x3_driver_id=None)
    middle = after_state(state, catalog, lineup)
    final = after_state(middle, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state, middle, final], catalog)
    with pytest.raises(account.AccountError, match="allow_penalties"):
        account.apply(tmp_path, 2026, proposal)
    assert session.posts == []
    assert account.audit(tmp_path) == []
    session.reads = 0
    assert (
        account.apply(tmp_path, 2026, proposal, allow_penalties=True)[
            "transfer_penalty"
        ]
        == 10
    )
    assert len(session.posts) == 2


def test_unknown_journal_step_status_cannot_be_treated_as_unsent(
    tmp_path, monkeypatch, state, catalog, proposal
):
    stages(state, catalog, proposal)
    session = install(monkeypatch, tmp_path, [state], catalog)
    with pytest.raises(account.AccountError):
        account.apply(tmp_path, 2026, proposal)
    rows = account._ledger(tmp_path)
    rows[0]["steps"][0]["status"] = "sent_by_another_version"
    account._save_ledger(tmp_path, rows)
    with pytest.raises(
        account.AccountError, match="Unrecognized combined apply journal; no replay"
    ):
        account.recover(tmp_path, 2026)
    assert len(session.posts) == 1
