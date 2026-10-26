from datetime import datetime, timezone

import pytest

from f1fantasy import training
from f1fantasy import cli
from f1fantasy.backtest import BacktestAsset, BacktestRow
from f1fantasy.data import DataError, Weekend
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
            assets = (
                BacktestAsset(
                    "d",
                    "Driver",
                    "DRIVER",
                    Estimate(3, 2 if event.sprint else 0, driver_race),
                    Estimate(3, 4 if event.sprint else 0, 20),
                    20,
                ),
                BacktestAsset(
                    "c",
                    "Team",
                    "CONSTRUCTOR",
                    Estimate(6, 3 if event.sprint else 0, driver_race + 10),
                    Estimate(6, 6 if event.sprint else 0, 30),
                    30,
                ),
            )
            return BacktestRow(
                event, 1, 1, 10, 10, 0, 1 if event.sprint else None, 10, assets
            )

        modern.append(row(10))
        legacy.append(row(20))
    return modern, legacy


def test_split_and_learned_weights_improve_unseen_races():
    current, older = synthetic_rows()
    entries = training.observations(current, older)
    artifact = training.fit_calibration(entries, 2026)
    assert artifact["trained_rounds"] == list(range(5, 11))
    assert artifact["validation_rounds"] == [11, 12, 13]
    assert artifact["test_rounds"] == [14, 15, 16]
    assert artifact["active"]
    assert artifact["weights"]["DRIVER"]["race"][0] < 1
    assert artifact["metrics"]["DRIVER"]["race"]["test"]["candidate_mae"] < 10
    assert artifact["metrics"]["DRIVER"]["sprint"]["promoted"] is False


def test_train_reuses_versioned_artifact_until_new_round(tmp_path, monkeypatch):
    current, older = synthetic_rows()
    monkeypatch.setattr(
        training, "season_weekends", lambda _: [r.weekend for r in current]
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


def test_invalid_weights_never_activate(tmp_path):
    path = training.model_path(2026, tmp_path)
    path.write_text(
        '{"version":1,"season":2026,"active":true,"last_completed_round":10,'
        '"weights":{"DRIVER":{"race":[2,0,0],"sprint":[1,0],"qualifying":[1,0]},'
        '"CONSTRUCTOR":{"race":[1,0,0],"sprint":[1,0],"qualifying":[1,0]}}}'
    )
    with pytest.raises(DataError, match="Invalid saved calibration weights"):
        training.load_model(2026, tmp_path)


def test_needs_chronological_train_validation_and_test_blocks():
    with pytest.raises(DataError, match="eight completed"):
        training.chronological_split([5, 6, 7, 8, 9, 10, 11])


def test_cli_train_outputs_machine_readable_model(monkeypatch, capsys):
    import json

    report = training.fit_calibration(training.observations(*synthetic_rows()), 2026)
    monkeypatch.setattr(cli, "train", lambda season, lookback: report)
    assert cli.main(["--season", "2026", "train", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["model"]["active"]
    assert payload["data"]["model"]["test_rounds"] == [14, 15, 16]
