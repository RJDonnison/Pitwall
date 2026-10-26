from datetime import datetime, timezone

import pytest

from f1fantasy import backtest, cli
from f1fantasy.data import Asset, DataError, Weekend
from f1fantasy.projections import Estimate


def test_rolling_evaluation_splits_sprint_and_regular(monkeypatch, capsys):
    targets = [
        Weekend(
            2026,
            i,
            f"Round {i}",
            i,
            datetime(2026, 4, i * 5, tzinfo=timezone.utc),
            i == 2,
            True,
            datetime(2026, 4, i * 5 + 1, tzinfo=timezone.utc),
        )
        for i in (1, 2)
    ]
    assets = (
        Asset("d", "Driver", "DRIVER", "team", 50, "AAA"),
        Asset("c", "Team", "CONSTRUCTOR", "team", 50),
    )
    monkeypatch.setattr(backtest, "season_weekends", lambda _: targets)
    requested = []

    def roster(gameday, *, require_recent):
        assert require_recent is False
        requested.append(gameday)
        return assets, datetime.now(timezone.utc)

    monkeypatch.setattr(backtest, "load_assets", roster)
    monkeypatch.setattr(
        backtest,
        "estimate_assets",
        lambda a, w, lookback, use_telemetry, use_risk, use_model, return_features: {
            (0, "d"): Estimate(2, 3 if w[0].sprint else 0, 5),
            (0, "c"): Estimate(3, 4 if w[0].sprint else 0, 6),
        },
    )
    monkeypatch.setattr(
        backtest,
        "completed_scores",
        lambda id_, sprint: {
            "d": (1, 4 if sprint else 0, 6),
            "c": (2, 5 if sprint else 0, 7),
        },
    )
    results = backtest.run_backtest(
        2026, count=2, now=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )
    assert requested == [1, 2]
    assert [r.sprint_error for r in results] == [None, 1.0]
    assert [r.driver_error for r in results] == [0.0, 1.0]
    assert results[0].baseline_driver_count == 0
    assert results[1].baseline_driver_count == 1
    assert results[1].baseline_driver_race_error == 0
    assert results[1].model_driver_race_error_on_baseline == 1
    assert results[1].race_bias == -1
    monkeypatch.setattr(cli, "run_backtest", lambda *args, **kwargs: results)
    assert cli.main(["--season", "2026", "backtest", "--races", "2"]) == 0
    printed = capsys.readouterr().out
    assert "Sprint (1 weekends)" in printed and "regular (1 weekends)" in printed
    assert (
        cli.main(
            ["--season", "2026", "backtest", "--races", "2", "--compare-telemetry"]
        )
        == 0
    )
    assert "telemetry comparison" in capsys.readouterr().out
    assert (
        cli.main(["--season", "2026", "backtest", "--races", "2", "--compare-risk"])
        == 0
    )
    printed = capsys.readouterr().out
    assert "Signed bias" in printed and "last-3 average" in printed
    assert "Sprint-risk comparison" in printed


def test_backtest_requires_completed_race(monkeypatch):
    weekend = Weekend(
        2026,
        1,
        "Future",
        1,
        datetime(2026, 4, 1, tzinfo=timezone.utc),
        False,
        False,
        datetime(2026, 4, 2, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(backtest, "season_weekends", lambda _: [weekend])
    with pytest.raises(DataError, match="finalized"):
        backtest.run_backtest(2026, now=datetime(2026, 4, 2, tzinfo=timezone.utc))


def test_budgeted_regret_uses_prelock_prices_and_realized_boost(monkeypatch, tmp_path):
    event = Weekend(
        2026,
        1,
        "Test",
        1,
        datetime(2026, 4, 1, tzinfo=timezone.utc),
        False,
        True,
        datetime(2026, 4, 2, tzinfo=timezone.utc),
    )
    assets = tuple(
        [Asset(str(i), f"D{i}", "DRIVER", str(i // 2), 50, f"D{i}") for i in range(20)]
        + [Asset(f"c{i}", f"T{i}", "CONSTRUCTOR", str(i), 100) for i in range(10)]
    )
    monkeypatch.setattr(backtest, "season_weekends", lambda _: [event])
    monkeypatch.setattr(
        backtest, "load_assets", lambda *_args, **_kwargs: (assets, None)
    )
    monkeypatch.setattr(backtest, "load_verified", lambda *_args: assets)
    monkeypatch.setattr(
        backtest,
        "estimate_assets",
        lambda *_args, **_kwargs: {
            (0, a.id): Estimate(0, 0, 100 - index) for index, a in enumerate(assets)
        },
    )
    monkeypatch.setattr(
        backtest,
        "completed_scores",
        lambda *_args: {a.id: (0, 0, float(index)) for index, a in enumerate(assets)},
    )
    result = backtest.run_backtest(
        2026, now=datetime(2026, 5, 1, tzinfo=timezone.utc), price_dir=tmp_path
    )[0]
    budgeted = result.selection["budgeted_initial_team"]
    assert budgeted["regret_points"] > 0
    assert budgeted["hindsight_best_points"] > budgeted["picked_actual_points"]
    assert budgeted["boost_driver_id"] in budgeted["selected_ids"]
