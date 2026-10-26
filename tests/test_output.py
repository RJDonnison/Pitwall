import json
from datetime import datetime, timezone

from f1fantasy import cli
from f1fantasy.backtest import BacktestAsset, BacktestRow
from f1fantasy.data import Asset, Snapshot, Statistic, StatisticsSnapshot, Weekend
from f1fantasy.projections import Estimate


def _live():
    assets = tuple(
        [
            Asset(str(i), f"Driver {i}", "DRIVER", str(i // 2), 50, f"D{i}")
            for i in range(20)
        ]
        + [Asset(f"c{i}", f"Team {i}", "CONSTRUCTOR", str(i), 50) for i in range(10)]
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = Weekend(2026, 1, "Opening", 1, now, True, False)
    return Snapshot(event, assets, now, now), [event]


def test_prices_init_recommend_statistics_json(tmp_path, monkeypatch, capsys):
    live, weekends = _live()
    monkeypatch.setattr(cli, "snapshot", lambda *_args, **_kwargs: (live, weekends))
    monkeypatch.setattr(
        cli,
        "estimate_assets",
        lambda assets, events, **_kwargs: {
            (0, a.id): Estimate(2, 3, 5) for a in assets
        },
    )
    monkeypatch.setattr(
        cli,
        "load_statistics",
        lambda _: StatisticsSnapshot(
            2026, (Statistic("0", "DRIVER", "Driver 0", 50, 20.0),), live.fetched_at
        ),
    )
    state = tmp_path / "team.json"

    assert cli.main(["--season", "2026", "prices", "--format", "json"]) == 0
    prices = json.loads(capsys.readouterr().out)
    assert prices["schema_version"] == 1 and prices["command"] == "prices"
    assert len(prices["data"]["assets"]) == 30
    assert prices["data"]["price_source"]["provisional"] is False

    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--state",
                str(state),
                "init",
                "--drivers",
                "0",
                "1",
                "2",
                "3",
                "4",
                "--constructors",
                "c0",
                "c1",
                "--budget",
                "100",
                "--format",
                "json",
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["data"]["budget_tenths_m"] == 1000
    assert state.exists()

    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--state",
                str(state),
                "recommend",
                "--races",
                "1",
                "--format",
                "json",
            ]
        )
        == 0
    )
    recommendation = json.loads(capsys.readouterr().out)
    lineup = recommendation["data"]["lineups"][0]
    assert len(lineup["drivers"]) == 5 and len(lineup["constructors"]) == 2
    assert lineup["boost_driver_id"] in {driver["id"] for driver in lineup["drivers"]}
    assert lineup["session_points_including_boost"]["sprint"] > 0

    assert cli.main(["--season", "2026", "statistics", "--format", "json"]) == 0
    statistics = json.loads(capsys.readouterr().out)
    assert statistics["data"]["entries"][0]["season_points"] == 20


def test_backtest_details_preload_and_error_json(monkeypatch, capsys):
    live, weekends = _live()
    event = weekends[0]
    detail = BacktestAsset(
        "0", "Driver 0", "DRIVER", Estimate(2, 3, 5), Estimate(1, 4, 6)
    )
    row = BacktestRow(event, 1, 1, 1.0, 2.0, 1.0, 1.0, 1.0, (detail,))
    monkeypatch.setattr(cli, "run_backtest", lambda *_args, **_kwargs: [row])
    assert (
        cli.main(
            [
                "--season",
                "2026",
                "backtest",
                "--races",
                "1",
                "--show-points",
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["data"]["rows"][0]["assets"][0]["actual_points"]["total"] == 11
    assert report["data"]["rows"][0]["mae_points"]["qualifying_all_assets"] == 1

    assert (
        cli.main(["--season", "2026", "backtest", "--races", "1", "--show-points"]) == 0
    )
    assert "Total 10.0→11.0 (-1.0)" in capsys.readouterr().out

    monkeypatch.setattr(cli, "cache_status", lambda: {2025: 4})
    assert cli.main(["preload", "--status", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["years"] == [
        {"season": 2025, "processed_sessions": 4}
    ]
    monkeypatch.setattr(cli, "preload", lambda **_kwargs: (2, 3, ["missing Q"]))
    assert cli.main(["preload", "--seasons", "1", "--format", "json"]) == 1
    partial = json.loads(capsys.readouterr().out)
    assert partial["status"] == "partial" and partial["data"]["unavailable"] == [
        "missing Q"
    ]

    assert cli.main(["recommend", "--races", "0", "--format", "json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["status"] == "error"


def test_clear_team_is_offline_idempotent_and_only_removes_selected_state(
    tmp_path, monkeypatch, capsys
):
    state = tmp_path / "team.json"
    unrelated = tmp_path / "keep.json"
    state.write_text('{"drivers": []}')
    unrelated.write_text("keep")
    monkeypatch.setattr(
        cli,
        "snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("clear-team must not fetch live data")
        ),
    )
    assert cli.main(["--state", str(state), "clear-team", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["command"] == "clear-team" and result["data"]["removed"] is True
    assert not state.exists() and unrelated.read_text() == "keep"
    assert cli.main(["--state", str(state), "clear-team"]) == 0
    assert "No locally imported team" in capsys.readouterr().out
