"""Season planning while interactive recommendations stay bounded."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from f1fantasy import account, cli, scheduler
from f1fantasy.data import DataError
from f1fantasy.projections import Estimate
from test_scheduler import setup, NOW
from test_v3_cli import game


def calendar(game, monkeypatch):
    live, state, _ = game
    weekends = [
        replace(
            live.weekend,
            round=10 + i,
            gameday_id=10 + i,
            first_session=live.weekend.first_session + timedelta(days=7 * i),
        )
        for i in range(6)
    ]
    monkeypatch.setattr(cli, "snapshot", lambda *a, **k: (live, weekends))
    monkeypatch.setattr(
        cli,
        "estimate_assets",
        lambda assets, events, **k: {
            (t, a.id): Estimate(0, 0, 500 if a.id == "5" and event.round == 15 else 10)
            for t, event in enumerate(events)
            for a in assets
        },
    )
    return live, state, weekends


def test_season_plans_beyond_five_rounds_and_saves_chip_for_late_gain(
    game, monkeypatch
):
    live, state, weekends = calendar(game, monkeypatch)
    args = cli._parser().parse_args(
        ["--season", "2026", "daemon", "run", "--season-plan"]
    )
    plans, _, _, _, _, reserves, _ = cli._plan(args, live, weekends, state)
    assert len(plans) == 6
    assert [plan.chip for plan in plans] == [None] * 5 + ["x3"]
    assert plans[-1].x3.id == "5"
    assert all(value == 0 for value in reserves.values())


def test_interactive_recommendation_defaults_and_options_remain_unchanged(
    game, monkeypatch, capsys
):
    _, _, path = game
    calendar(game, monkeypatch)
    prefix = [
        "--season",
        "2026",
        "--state",
        str(path),
        "recommend",
        "--no-account",
        "--format",
        "json",
    ]
    assert cli.main(prefix) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert len(data["lineups"]) == 3
    assert data["chip_reserve_points"]["x3"] == 40
    assert cli.main(prefix + ["--races", "5"]) == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["lineups"]) == 5


def test_season_apply_submits_only_current_round_and_returns_future_intent(
    game, monkeypatch, capsys
):
    live, state, weekends = calendar(game, monkeypatch)
    state.update(gameday_id=10, baseline_ids=state["drivers"] + state["constructors"])
    monkeypatch.setattr(account, "show", lambda *a: state)
    submitted = []

    def apply(*args):
        submitted.append(args[-2])
        return {"apply_status": "verified"}

    monkeypatch.setattr(account, "apply", apply)
    args = cli._parser().parse_args(
        ["--season", "2026", "daemon", "run", "--season-plan"]
    )
    args.account_action, args.replan, args.final_fix, args.format = (
        "apply",
        True,
        False,
        "json",
    )
    assert cli._account_command(args) == 0
    plan = json.loads(capsys.readouterr().out)["data"]["season_plan"]
    assert len(submitted) == 1 and submitted[0]["gameday_id"] == live.weekend.gameday_id
    assert plan["rounds"][-1]["gameday_id"] == weekends[-1].gameday_id
    assert plan["rounds"][-1]["chip"] == "x3"
    assert plan["projected_total_points"] == pytest.approx(
        sum(r["expected_points"] for r in plan["rounds"])
    )
    assert plan["future_prices_assumed_constant"] is True


def test_unknown_limitless_restoration_cannot_silently_shorten_season_plan(
    game, monkeypatch
):
    live, state, weekends = calendar(game, monkeypatch)
    state["active_chip"] = "limitless"
    args = cli._parser().parse_args(
        ["--season", "2026", "daemon", "run", "--season-plan"]
    )
    with pytest.raises(DataError, match="verified Limitless restoration"):
        cli._plan(args, live, weekends, state)


def test_scheduler_advances_rounds_persists_season_intent_and_preserves_used_chip_inventory(
    setup,
):
    path, live, policy, _, _, tick = setup
    policy.update(season_plan=True, allow_penalties=True)
    intent = {"season": 2026, "rounds": [{"gameday_id": 19}, {"gameday_id": 20}]}
    inventories = []
    live["available_chips"] = ["x3"]

    def execute(job):
        assert job["policy"]["season_plan"] is True
        inventories.append(list(live["available_chips"]))
        return dict(apply_status="verified", season_plan=intent)

    first = tick(runner=execute)
    assert first["planning_scope"] == "remaining_season"
    early = next(j for j in first["jobs"].values() if j["stage"] == "early")
    assert scheduler.status(path)["jobs"][early["id"]]["season_plan"] == intent
    tick(runner=execute)
    assert len(inventories) == 1
    live.update(gameday_id=20, available_chips=[])
    second = tick(runner=execute)
    assert inventories == [["x3"], []]
    assert len([j for j in second["jobs"].values() if j["status"] == "verified"]) == 2


def test_old_interrupted_jobs_do_not_inherit_new_season_mode(
    setup, monkeypatch, capsys
):
    path, live, _, calls, _, tick = setup

    def crash(job):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tick(runner=crash)
    monkeypatch.setattr(account, "show", lambda *a: deepcopy(live))
    original = scheduler._tick
    monkeypatch.setattr(scheduler, "_tick", lambda *args: original(*args[:-1], now=NOW))

    def apply(options):
        assert options.season_plan is False
        assert options.allow_penalties is False
        cli._json_output("account apply", {"apply_status": "verified"})

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
                "--season-plan",
                "--allow-penalties",
            ]
        )
        == 0
    )


def test_invalid_persisted_season_mode_fails_closed(setup):
    _, _, policy, _, _, tick = setup
    policy["season_plan"] = "yes"
    with pytest.raises(DataError, match="season planning mode"):
        tick()
