"""Restoration follows the draft at activation, not the net-transfer baseline."""

from f1fantasy import account
from f1fantasy.optimizer import optimize
from f1fantasy.projections import Estimate
from test_account import state, catalog, proposal, install, raw, fixture, history
from test_chips import fixture as chip_fixture, ids


def test_limitless_restores_activation_draft_instead_of_net_baseline():
    assets, weekends, estimates, baseline = chip_fixture(2)
    draft = frozenset({"0", "1", "2", "3", "5", "c0", "c1"})
    forecast = {key: Estimate(0, 0, 0) for key in estimates}
    wanted = {"0", "1", "2", "3", "4", "c0", "c2"}
    for asset in assets:
        forecast[0, asset.id] = Estimate(0, 0, 10 if asset.id in baseline else 0)
        forecast[1, asset.id] = Estimate(0, 0, 100 if asset.id in wanted else 0)
    result = optimize(
        assets,
        weekends,
        forecast,
        100,
        baseline,
        active_chip="limitless",
        limitless_restore=draft,
    )
    assert ids(result[0]) == baseline
    assert ids(result[1]) == wanted
    assert result[1].transfers == 2  # Only one if the old baseline were restored.
    assert result[1].transfer_penalty == 0


def test_limitless_records_and_exposes_actual_activation_draft(
    tmp_path, monkeypatch, state, catalog, proposal
):
    state["drivers"][-1] = "7"
    state.update(net_transfers=1, transfers_left=1)
    proposal.update(chip="limitless")
    _, _, expected = account._plan(state, catalog, account._proposal(proposal), False)
    after = dict(state, **expected)
    session = install(monkeypatch, tmp_path, [state, after, after], catalog)
    assert account.apply(tmp_path, 2026, proposal)["apply_status"] == "verified"
    journal = account._ledger(tmp_path)
    assert (
        "7" in journal[0]["restoration_ids"]
        and "5" not in journal[0]["restoration_ids"]
    )
    shown = account.show(tmp_path, 2026)
    assert shown["limitless_restoration_ids"] == journal[0]["restoration_ids"]
    assert len(session.posts) == 1


def test_active_limitless_edit_preserves_recorded_restoration(
    tmp_path, monkeypatch, state, catalog, proposal
):
    proposal.update(chip="limitless")
    _, _, expected = account._plan(state, catalog, account._proposal(proposal), False)
    active = dict(state, **expected)
    install(monkeypatch, tmp_path, [state, active], catalog)
    account.apply(tmp_path, 2026, proposal)
    original = account._ledger(tmp_path)[0]["restoration_ids"]
    edited = dict(proposal, drivers=["1", "2", "3", "4", "7"])
    path, payload, second = account._plan(
        active, catalog, account._proposal(edited), False
    )
    assert path == account.TEAM + "transferteam"
    assert payload["boosterId"] == 1
    after = dict(active, **second)
    install(monkeypatch, tmp_path, [active, after, after], catalog)
    assert account.apply(tmp_path, 2026, edited)["apply_status"] == "verified"
    assert account.show(tmp_path, 2026)["limitless_restoration_ids"] == original


def test_active_limitless_can_optimize_with_verified_restoration():
    assets, weekends, estimates, baseline = chip_fixture(2)
    result = optimize(
        assets,
        weekends,
        estimates,
        100,
        baseline,
        active_chip="limitless",
        limitless_restore=baseline,
    )
    assert result[0].chip == "limitless"
    assert result[1].chip is None
