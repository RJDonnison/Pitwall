"""CLI integration tests for chip semantics and the account trust boundary."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from f1fantasy import account, cli, data
from f1fantasy.chips import ChipValues
from f1fantasy.data import Asset, Snapshot, Weekend
from f1fantasy.projections import Estimate


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(account, "recover", lambda *a, **k: None)
    now = datetime.now(timezone.utc)
    assets = tuple(
        [Asset(str(i), f"D{i}", "DRIVER", str(i // 2), 50) for i in range(6)]
        + [Asset(f"c{i}", f"C{i}", "CONSTRUCTOR", str(i), 100) for i in range(3)]
    )
    event = Weekend(2026, 10, "Test", 10, now + timedelta(days=2), False, False)
    live = Snapshot(event, assets, now, now)
    state = {
        "season": 2026,
        "drivers": [str(i) for i in range(5)],
        "constructors": ["c0", "c1"],
        "boost_driver_id": "0",
        "budget": 100,
        "carry": 0,
        "available_chips": ["x3", "final_fix"],
        "completed_first_weekend": True,
    }
    path = tmp_path / "team.json"
    path.write_text(json.dumps(state))
    monkeypatch.setattr(cli, "snapshot", lambda *a, **k: (live, [event]))
    monkeypatch.setattr(
        cli,
        "estimate_assets",
        lambda assets, events, **k: {
            (t, a.id): Estimate(1, 0, i + 2)
            for t, _ in enumerate(events)
            for i, a in enumerate(assets)
        },
    )
    return live, state, path


def run(path, *args):
    return cli.main(
        ["--season", "2026", "--state", str(path), *args, "--format", "json"]
    )


def test_chips_inventory_is_explicit_and_offline(game, capsys):
    _, state, path = game
    assert run(path, "chips", "--no-account") == 0
    value = json.loads(capsys.readouterr().out)["data"]
    assert value["available_chips"] == state["available_chips"]
    assert value["inventory_verified"] is False
    path.unlink()
    assert run(path, "chips", "--no-account") == 0
    assert json.loads(capsys.readouterr().out)["data"]["available_chips"] is None


def test_account_and_chip_planning_are_enabled_by_default(game, monkeypatch, capsys):
    _, state, path = game
    state.update(gameday_id=10, eligible_chips=["x3"])
    reads = []

    def show(*args):
        reads.append("show")
        return state

    monkeypatch.setattr(account, "show", show)
    assert run(path, "recommend", "--races", "1") == 0
    result = json.loads(capsys.readouterr().out)["data"]
    assert result["account_synced"] is True
    assert result["lineups"][0]["chip"] == "x3"
    assert run(path, "chips") == 0
    assert json.loads(capsys.readouterr().out)["data"]["inventory_verified"] is True
    assert reads == ["show", "show"]


def test_chip_recommendation_reports_x3_sessions_and_terminal_reserve(game, capsys):
    _, _, path = game
    assert run(path, "recommend", "--no-account", "--chip", "x3", "--races", "1") == 0
    value = json.loads(capsys.readouterr().out)["data"]
    lineup = value["lineups"][0]
    assert lineup["chip"] == "x3"
    assert lineup["x3_driver_id"] != lineup["boost_driver_id"]
    assert sum(lineup["session_points_including_boost"].values()) == pytest.approx(
        lineup["expected_points"]
    )
    assert all(v == 0 for v in value["chip_reserve_points"].values())


def test_recommendation_reports_empirical_history_coverage(game, monkeypatch, capsys):
    live, state, path = game
    state["available_chips"] = ["no_negative"]
    path.write_text(json.dumps(state))
    monkeypatch.setattr(
        cli,
        "load_chip_values",
        lambda *a: ChipValues(
            no_negative={(0, a.id): Estimate(0, 0, 1) for a in live.assets},
            history_gamedays={0: (7, 8, 9)},
            skipped_history_gamedays=(5, 6),
        ),
    )
    assert run(path, "recommend", "--no-account", "--races", "1") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["data"]["chip_history"] == {
        "sample_gamedays": {"0": [7, 8, 9]},
        "skipped_null_score_gamedays": [5, 6],
    }
    assert any("excluded official null-score" in w for w in output["warnings"])


def test_chip_inventory_and_reserve_failures_do_not_produce_recommendations(
    game, capsys
):
    _, state, path = game
    del state["available_chips"]
    path.write_text(json.dumps(state))
    assert run(path, "recommend", "--no-account") == 1
    result = capsys.readouterr()
    assert result.out == "" and "inventory" in result.err
    state["available_chips"] = ["x3"]
    path.write_text(json.dumps(state))
    assert run(path, "recommend", "--no-account", "--chip-reserve", "x3=nan") == 1
    result = capsys.readouterr()
    assert result.out == "" and "reserve" in result.err


def test_account_apply_reforecasts_and_uses_original_net_baseline(
    game, monkeypatch, capsys
):
    live, state, path = game
    baseline = state["drivers"] + state["constructors"]
    state.update(gameday_id=10, baseline_ids=baseline, eligible_chips=["x3"])
    # A prior in-week draft must not redefine transfer accounting.
    state["drivers"] = ["1", "2", "3", "4", "5"]
    calls = []
    monkeypatch.setattr(account, "show", lambda *a: state)
    original_estimator = cli.estimate_assets

    def estimate(*args, **kwargs):
        calls.append("forecast")
        return original_estimator(*args, **kwargs)

    monkeypatch.setattr(cli, "estimate_assets", estimate)

    def apply(directory, season, proposal, allow_penalties):
        assert calls == ["forecast"]
        assert proposal["chip"] == "x3"
        assert proposal["baseline_ids"] == baseline
        proposed = set(proposal["drivers"] + proposal["constructors"])
        assert (
            proposal["expected_transfer_penalty"]
            == max(0, len(set(baseline) - proposed) - 2) * 10
        )
        calls.append("apply")
        return {"apply_status": "verified"}

    monkeypatch.setattr(account, "apply", apply)
    assert run(path, "account", "apply", "--races", "1") == 0
    assert calls == ["forecast", "apply"]
    assert json.loads(capsys.readouterr().out)["data"]["apply_status"] == "verified"


def test_account_event_conflict_never_submits(game, monkeypatch, capsys):
    _, state, path = game
    state["gameday_id"] = 11
    monkeypatch.setattr(account, "show", lambda *a: state)
    monkeypatch.setattr(account, "apply", lambda *a: pytest.fail("must not submit"))
    assert run(path, "account", "apply") == 1
    result = capsys.readouterr()
    assert result.out == "" and "event" in result.err


def test_cli_recovers_interrupted_chip_before_reforecast(game, monkeypatch, capsys):
    _, _, path = game
    monkeypatch.setattr(
        account, "recover", lambda *a: {"apply_status": "verified", "active_chip": "x3"}
    )
    monkeypatch.setattr(
        account, "show", lambda *a: pytest.fail("recovery already read back")
    )
    monkeypatch.setattr(
        cli,
        "estimate_assets",
        lambda *a, **k: pytest.fail("no new plan before recovery"),
    )
    assert run(path, "account", "apply") == 0
    assert json.loads(capsys.readouterr().out)["data"]["active_chip"] == "x3"


def test_remote_recommendation_enforces_current_eligibility(game, monkeypatch, capsys):
    _, state, path = game
    state.update(gameday_id=10, eligible_chips=[])
    monkeypatch.setattr(account, "show", lambda *a: state)
    assert run(path, "recommend", "--account", "--chip", "x3", "--races", "1") == 1
    assert "ineligible" in capsys.readouterr().err


def test_active_x3_recommendation_preserves_chip_even_with_no_chips_flag(
    game, monkeypatch, capsys
):
    _, state, path = game
    state.update(
        gameday_id=10,
        active_chip="x3",
        eligible_chips=[],
        available_chips=["final_fix"],
    )
    monkeypatch.setattr(account, "show", lambda *a: state)
    assert run(path, "recommend", "--no-chips") == 0
    value = json.loads(capsys.readouterr().out)["data"]
    assert value["lineups"][0]["chip"] == "x3"
    assert value["lineups"][0]["x3_driver_id"] != value["lineups"][0]["boost_driver_id"]


def test_explicit_replan_still_recovers_pending_work_before_forecasting(
    game, monkeypatch, capsys
):
    _, _, path = game

    def recover(*a, **kwargs):
        assert kwargs == {"confirm_completed": False}
        return {"apply_status": "verified"}

    monkeypatch.setattr(account, "recover", recover)
    monkeypatch.setattr(
        account, "show", lambda *a: pytest.fail("pending recovery wins")
    )
    assert run(path, "account", "apply", "--replan") == 0
    assert json.loads(capsys.readouterr().out)["data"]["apply_status"] == "verified"


def test_account_final_fix_preview_and_apply_use_only_remaining_points(
    game, monkeypatch, capsys
):
    live, state, path = game
    state.update(
        budget_tenths_m=1000,
        baseline_ids=state["drivers"] + state["constructors"],
        transfer_penalty=10,
        retained_points={"0": {"Qualifying": 7}},
    )
    context = dict(
        state=state,
        assets=live.assets,
        weekend=live.weekend,
        remaining_sessions=["race"],
        accrued_points=37,
        eligible=True,
        window={"open": True, "raceday": 20},
    )
    monkeypatch.setattr(account, "final_fix_context", lambda *a: context)
    assert run(path, "chips", "--final-fix") == 0
    result = json.loads(capsys.readouterr().out)["data"]
    assert result["provisional"] is False
    assert result["accrued_points"] == 37
    assert result["out_id"] == "0" and result["in_id"] == "5"
    assert result["expected_total_points"] == pytest.approx(
        37 + result["remaining_points"] - 10
    )

    def apply(*args):
        proposal = args[-1]
        assert proposal["chip"] == "final_fix"
        assert proposal["outgoing_id"] == "0" and proposal["incoming_id"] == "5"
        assert proposal["boost_driver_id"] == "5"
        assert proposal["expected_transfer_penalty"] == 10
        assert proposal["retained_points"] == state["retained_points"]
        return {"apply_status": "verified"}

    monkeypatch.setattr(account, "apply_final_fix", apply)
    assert run(path, "account", "apply", "--final-fix") == 0
    assert json.loads(capsys.readouterr().out)["data"]["apply_status"] == "verified"


def test_account_final_fix_closed_window_never_forecasts_or_submits(
    game, monkeypatch, capsys
):
    live, state, path = game
    monkeypatch.setattr(
        account,
        "final_fix_context",
        lambda *a: dict(
            state=state, assets=live.assets, weekend=live.weekend, eligible=False
        ),
    )
    monkeypatch.setattr(
        cli, "estimate_assets", lambda *a, **k: pytest.fail("closed window")
    )
    assert run(path, "account", "apply", "--final-fix") == 1
    output = capsys.readouterr()
    assert output.out == "" and "authoritative server window" in output.err


def test_final_fix_without_account_needs_explicit_provisional_file(game, capsys):
    _, _, path = game
    assert run(path, "chips", "--no-account", "--final-fix") == 1
    assert "provisional input file" in capsys.readouterr().err


def test_active_limitless_missing_restoration_limits_horizon_and_allows_overcap(
    game, monkeypatch, capsys
):
    _, state, path = game
    state.update(
        gameday_id=10,
        active_chip="limitless",
        budget=1,
        eligible_chips=[],
        unlimited_transfers=True,
    )
    monkeypatch.setattr(account, "show", lambda *a: state)
    assert run(path, "recommend", "--no-chips", "--races", "3") == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["data"]["lineups"]) == 1
    assert result["data"]["lineups"][0]["chip"] == "limitless"
    assert (
        result["data"]["lineups"][0]["cost_tenths_m"]
        > result["data"]["budget_tenths_m"]
    )
    assert any("restoration draft" in warning for warning in result["warnings"])


def test_account_final_fix_keeps_chip_when_no_swap_improves_remaining_score(
    game, monkeypatch, capsys
):
    live, state, path = game
    state.update(budget_tenths_m=1000, transfer_penalty=0)
    monkeypatch.setattr(
        account,
        "final_fix_context",
        lambda *a: dict(
            state=state,
            assets=live.assets,
            weekend=live.weekend,
            remaining_sessions=["race"],
            accrued_points=37,
            eligible=True,
            window={"open": True},
        ),
    )
    monkeypatch.setattr(
        cli,
        "estimate_assets",
        lambda *a, **k: {(0, item.id): Estimate(999, 999, 0) for item in live.assets},
    )
    monkeypatch.setattr(
        account,
        "apply_final_fix",
        lambda *a: pytest.fail("Do not spend a chip without an improvement"),
    )
    assert run(path, "account", "apply", "--final-fix") == 0
    result = json.loads(capsys.readouterr().out)["data"]
    assert result["apply_status"] == "unchanged"
    assert result["remaining_points"] == 0 and result["expected_total_points"] == 37


def test_account_audit_is_offline_and_connect_requires_explicit_team(
    game, monkeypatch, capsys
):
    _, _, path = game
    monkeypatch.setattr(account, "audit", lambda *a: [{"status": "unknown"}])
    assert run(path, "account", "audit") == 0
    assert json.loads(capsys.readouterr().out)["data"]["entries"] == [
        {"status": "unknown"}
    ]
    assert run(path, "account", "connect") == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_arguments"


def test_final_fix_preview_is_future_only_and_explicitly_provisional(
    game, tmp_path, monkeypatch, capsys
):
    live, state, path = game
    now = datetime.now(timezone.utc)
    event = replace(live.weekend, first_session=now - timedelta(days=1))
    spec = {
        "gameday_id": event.gameday_id,
        "window_open_utc": (now - timedelta(hours=1)).isoformat(),
        "window_close_utc": (now + timedelta(hours=1)).isoformat(),
        "remaining_sessions": ["race"],
        "accrued_points": 37,
        "remaining_points": {
            a.id: {"qualifying": 0, "sprint": 0, "race": 10 if a.id == "5" else 1}
            for a in live.assets
        },
    }
    source = tmp_path / "remaining.json"
    source.write_text(json.dumps(spec))
    monkeypatch.setattr(data, "season_weekends", lambda *a: [event])
    monkeypatch.setattr(data, "load_assets", lambda *a: (live.assets, now))
    monkeypatch.setattr(data, "load_statistics", lambda *a: {})
    assert run(path, "chips", "--no-account", "--final-fix", str(source)) == 0
    value = json.loads(capsys.readouterr().out)["data"]
    assert value["provisional"] is True and value["accrued_points"] == 37
    assert value["in_id"] == "5"
    assert value["boost_driver_id"] == "5"
    spec["remaining_points"]["5"]["qualifying"] = 50
    source.write_text(json.dumps(spec))
    assert run(path, "chips", "--no-account", "--final-fix", str(source)) == 1
    assert "elapsed session" in capsys.readouterr().err
