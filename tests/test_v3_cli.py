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
    monkeypatch.setattr(account, "recover", lambda *a: None)
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
    assert run(path, "chips") == 0
    value = json.loads(capsys.readouterr().out)["data"]
    assert value["available_chips"] == state["available_chips"]
    assert value["inventory_verified"] is False
    path.unlink()
    assert run(path, "chips") == 0
    assert json.loads(capsys.readouterr().out)["data"]["available_chips"] is None


def test_chip_recommendation_reports_x3_sessions_and_terminal_reserve(game, capsys):
    _, _, path = game
    assert run(path, "recommend", "--chips", "--chip", "x3", "--races", "1") == 0
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
    assert run(path, "recommend", "--chips", "--races", "1") == 0
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
    assert run(path, "recommend", "--chips") == 1
    result = capsys.readouterr()
    assert result.out == "" and "inventory" in result.err
    state["available_chips"] = ["x3"]
    path.write_text(json.dumps(state))
    assert run(path, "recommend", "--chips", "--chip-reserve", "x3=nan") == 1
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
    assert run(path, "chips", "--final-fix", str(source)) == 0
    value = json.loads(capsys.readouterr().out)["data"]
    assert value["provisional"] is True and value["accrued_points"] == 37
    assert value["in_id"] == "5"
    assert value["boost_driver_id"] == "5"
    spec["remaining_points"]["5"]["qualifying"] = 50
    source.write_text(json.dumps(spec))
    assert run(path, "chips", "--final-fix", str(source)) == 1
    assert "elapsed session" in capsys.readouterr().err
