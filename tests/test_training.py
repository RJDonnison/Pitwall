from datetime import datetime, timezone

import pytest

from f1fantasy import training
from f1fantasy import cli
from f1fantasy.backtest import BacktestAsset, BacktestRow
from f1fantasy.data import Asset, DataError, Weekend
from f1fantasy.prior_history import PriorWeek
from f1fantasy.projections import Estimate


def synthetic_rows():
    modern, legacy = [], []
    for round_number in range(5, 17):
        event = Weekend(
            2026,
            round_number,
            f"Round {round_number}",
            round_number,
            datetime(2026, 4, round_number, tzinfo=timezone.utc),
            round_number in (6, 11, 16),
            False,
            datetime(2026, 4, round_number, 3, tzinfo=timezone.utc),
        )

        def row(driver_race):
            def features(q_points, sprint_points, race_points, prior_form):
                return {
                    phase: {
                        "baseline": baseline,
                        "fastf1_form": baseline,
                        "official_form": prior_form,
                        "recent3": prior_form,
                        "team_form": prior_form,
                        "circuit_form": baseline,
                        "telemetry_delta": 0,
                        "severe_probability": 0,
                        "classified_points": prior_form,
                    }
                    for phase, baseline in (
                        ("qualifying", q_points),
                        ("sprint", sprint_points),
                        ("race", race_points),
                    )
                }

            assets = (
                BacktestAsset(
                    "d",
                    "Driver",
                    "DRIVER",
                    Estimate(3, 2 if event.sprint else 0, driver_race),
                    Estimate(3, 4 if event.sprint else 0, 20),
                    20,
                    features(3, 2 if event.sprint else 0, driver_race, 20),
                ),
                BacktestAsset(
                    "c",
                    "Team",
                    "CONSTRUCTOR",
                    Estimate(6, 3 if event.sprint else 0, driver_race + 10),
                    Estimate(6, 6 if event.sprint else 0, 30),
                    30,
                    features(6, 3 if event.sprint else 0, driver_race + 10, 30),
                ),
            )
            return BacktestRow(
                event, 1, 1, 10, 10, 0, 1 if event.sprint else None, 10, assets
            )

        modern.append(row(10))
        legacy.append(row(20))
    return modern, legacy


def prior_weeks():
    asset = Asset("d", "Driver", "DRIVER", "team", 30, "DDD")
    team = Asset("c", "Team", "CONSTRUCTOR", "team", 30)
    return [
        PriorWeek(
            Weekend(
                2025,
                round_number,
                f"Prior {round_number}",
                round_number,
                datetime(2025, 4, round_number, tzinfo=timezone.utc),
                False,
                True,
            ),
            (asset, team),
            {"d": Estimate(3, 0, 20), "c": Estimate(6, 0, 30)},
        )
        for round_number in range(1, 9)
    ]


def test_previous_season_seed_then_test_each_current_race_before_learning_it():
    current, older = synthetic_rows()
    prior = training.prior_observations(prior_weeks())
    artifact = training.replay_calibration(
        prior, training.observations(current, older), 2026, "fastf1_proxy"
    )
    assert artifact["prior_season"] == 2025
    assert artifact["replay_rounds"] == list(range(5, 17))
    first = artifact["weekly"][0]["errors"]["DRIVER.race"]
    second = artifact["weekly"][1]["errors"]["DRIVER.race"]
    assert first["prior_examples"] == 5  # no current-season result before first test
    assert first["replay_mae"] > second["replay_mae"]
    assert second["prior_examples"] == 6  # first test added only afterwards
    assert artifact["active"]
    assert artifact["weights"]["DRIVER"]["race"][0] < 1
    assert artifact["metrics"]["DRIVER"]["sprint"]["promoted"] is False


def test_first_race_is_predicted_before_it_can_train_second_race():
    current, legacy = [], []
    for number in (1, 2, 3):
        event = Weekend(
            2026,
            number,
            f"Round {number}",
            number,
            datetime(2026, 3, number, tzinfo=timezone.utc),
            False,
            True,
        )

        def row(driver_race):
            assets = (
                BacktestAsset(
                    "d",
                    "Driver",
                    "DRIVER",
                    Estimate(3, 0, driver_race),
                    Estimate(3, 0, 20),
                    20,
                ),
                BacktestAsset(
                    "c",
                    "Team",
                    "CONSTRUCTOR",
                    Estimate(6, 0, driver_race + 10),
                    Estimate(6, 0, 30),
                    30,
                ),
            )
            return BacktestRow(event, 1, 1, 10, 10, 0, None, 10, assets)

        current.append(row(10))
        legacy.append(row(20))
    result = training.replay_calibration(
        training.prior_observations(prior_weeks()),
        training.observations(current, legacy),
        2026,
        "fastf1_proxy",
    )
    assert result["replay_rounds"] == [1, 2, 3]
    first = result["weekly"][0]["errors"]["DRIVER.race"]
    second = result["weekly"][1]["errors"]["DRIVER.race"]
    assert first["prior_examples"] == 5
    assert second["prior_examples"] == 6
    assert first["replay_mae"] > second["replay_mae"]


def test_train_reuses_versioned_artifact_until_new_round(tmp_path, monkeypatch):
    current, older = synthetic_rows()
    monkeypatch.setattr(
        training, "season_weekends", lambda _: [r.weekend for r in current]
    )
    monkeypatch.setattr(
        training,
        "load_previous_season",
        lambda *_args, **_kwargs: (prior_weeks(), "fastf1_proxy"),
    )
    calls = []

    def backtest(*_args, use_risk=True, **_kwargs):
        calls.append(use_risk)
        return current if use_risk else older

    monkeypatch.setattr(training, "run_backtest", backtest)
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    first = training.train(2026, directory=tmp_path, now=now)
    assert calls == [True, False]
    assert training.model_path(2026, tmp_path).exists()
    assert training.load_model(2026, tmp_path)["active"] == first["active"]
    assert training.train(2026, directory=tmp_path, now=now) == first
    assert calls == [True, False]
    with pytest.raises(DataError, match="different lookback"):
        training.train(2026, directory=tmp_path, now=now, lookback=3)


def test_official_prior_import_replaces_approximate_source(tmp_path, monkeypatch):
    current, older = synthetic_rows()
    monkeypatch.setattr(
        training, "season_weekends", lambda _: [r.weekend for r in current]
    )
    monkeypatch.setattr(
        training,
        "run_backtest",
        lambda *_args, use_risk=True, **_kwargs: current if use_risk else older,
    )
    monkeypatch.setattr(
        training,
        "load_previous_season",
        lambda *_args, official_file=None, **_kwargs: (
            prior_weeks(),
            "imported_official" if official_file else "fastf1_proxy",
        ),
    )
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    proxy = training.train(2026, directory=tmp_path, now=now)
    imported = training.train(
        2026, directory=tmp_path, now=now, prior_scores_file=tmp_path / "official.json"
    )
    assert proxy["prior_source"] == "fastf1_proxy"
    assert imported["prior_source"] == "imported_official"
    assert imported["prior_example_weight"] > proxy["prior_example_weight"]


def test_invalid_weights_never_activate(tmp_path):
    path = training.model_path(2026, tmp_path)
    path.write_text(
        '{"version":7,"season":2026,"active":true,"last_completed_round":10,'
        '"weights":{"DRIVER":{"race":[2,0,0],"sprint":[1,0],"qualifying":[1,0]},'
        '"CONSTRUCTOR":{"race":[1,0,0],"sprint":[1,0],"qualifying":[1,0]}}}'
    )
    with pytest.raises(DataError, match="Invalid saved calibration weights"):
        training.load_model(2026, tmp_path)


def test_replay_requires_earlier_training_events():
    with pytest.raises(DataError, match="previous-season"):
        training.replay_calibration(
            [],
            [training.Observation(1, "DRIVER", "race", 5, (4, 4, 4))],
            2026,
            "fastf1_proxy",
        )


def test_can_warm_start_before_current_seasons_first_race(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "season_weekends", lambda _: [])
    monkeypatch.setattr(
        training,
        "load_previous_season",
        lambda *_args, **_kwargs: (prior_weeks(), "fastf1_proxy"),
    )
    monkeypatch.setattr(
        training,
        "run_backtest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no current race to test")
        ),
    )
    result = training.train(
        2026, directory=tmp_path, now=datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    assert result["last_completed_round"] == 0
    assert result["replay_rounds"] == []
    assert result["prior_examples"] > 0
    assert not result["active"]  # proxy labels alone cannot validate Fantasy MAE


def test_current_official_scores_outweigh_approximate_prior_labels():
    samples = [
        training.Observation(n, "DRIVER", "race", 10, (0, 10), "fastf1_proxy")
        for n in range(4)
    ]
    samples.append(training.Observation(1, "DRIVER", "race", 10, (10, 0)))
    assert training._fit(samples, 2)[0] > 0.9


def test_cli_train_outputs_machine_readable_model(monkeypatch, capsys):
    import json

    report = training.replay_calibration(
        training.prior_observations(prior_weeks()),
        training.observations(*synthetic_rows()),
        2026,
        "fastf1_proxy",
    )
    monkeypatch.setattr(
        cli, "train", lambda season, lookback, prior_scores_file: report
    )
    assert cli.main(["--season", "2026", "train", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["model"]["active"]
    assert payload["data"]["model"]["replay_rounds"] == list(range(5, 17))
