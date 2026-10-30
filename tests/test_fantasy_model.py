"""Independent leakage, scoring-target and adoption checks for Fantasy fitting."""

from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pytest

from f1fantasy import fantasy_model, projections, racing_model, public_history
from f1fantasy.data import Asset, Weekend


def scenario(monkeypatch):
    assets = tuple(
        [
            Asset(str(i), f"Driver {i}", "DRIVER", str(i // 2), 50, f"D{i}")
            for i in range(4)
        ]
        + [Asset(f"c{i}", f"Team {i}", "CONSTRUCTOR", str(i), 50) for i in range(2)]
    )
    origin = datetime(2026, 1, 10, tzinfo=timezone.utc)
    racing = [
        dict(season=2025, round=1, end="2025-12-01T20:00:00+00:00", sessions={"R": []})
    ]
    fantasy, events = {}, {}
    for number in range(1, 9):
        start = origin + timedelta(days=7 * number)
        end = start + timedelta(hours=6)
        racing.append(
            dict(
                season=2026,
                round=number,
                name=f"Race {number}",
                race_start_utc=start.isoformat(),
                end=end.isoformat(),
                sessions={
                    "Q": [],
                    "R": [dict(tla=a.tla) for a in assets if a.kind == "DRIVER"],
                },
            )
        )
        events[str(number)] = end.isoformat()
        fantasy[str(number)] = [
            dict(
                PlayerId=a.id,
                QualifyingPoints=10 + number,
                RacePoints=-999,
                SprintPoints="",
                GamedayPoints=30 + 3 * number,
            )
            for a in assets
        ]
    document = dict(racing=racing, fantasy=fantasy, fantasy_events=events)
    monkeypatch.setattr(racing_model, "timed", lambda history: True)
    monkeypatch.setattr(
        racing_model, "evaluate", lambda history, **kw: dict(parameters={})
    )
    current = {}

    def features(assets, weekend, history, labels, parameters, telemetry, seed):
        assert all(
            public_history.date(r["end"]) < weekend.first_session for r in history
        )
        assert all(r["event"] < weekend.round for r in labels)
        current["round"] = weekend.round
        return {
            (a.id, k): np.array([weekend.round, 0.0])
            for a in assets
            for k in ("Q", "R")
        }

    monkeypatch.setattr(fantasy_model, "_features", features)
    original = fantasy_model._predict

    def predict(train, targets, config):
        assert all(r["event"] < current["round"] for r in train)
        return original(train, targets, config)

    monkeypatch.setattr(fantasy_model, "_predict", predict)
    monkeypatch.setattr(
        projections,
        "_estimate_legacy",
        lambda assets, weekends, **kw: {
            (0, a.id): projections.Estimate(0, 0, 0) for a in assets
        },
    )
    fantasy_model._fit.cache_clear()
    return assets, document


def test_fit_has_no_same_weekend_training_and_uses_final_fantasy_totals(monkeypatch):
    assets, document = scenario(monkeypatch)
    result = fantasy_model._fit(json.dumps(document), assets, False)
    assert result["folds"]
    for row in result["folds"]:
        assert max(row["training_rounds"]) < row["round"]
        assert row["actual"] == (
            10 + row["round"] if row["session"] == "Q" else 20 + 2 * row["round"]
        )
    assert result["groups"]["DRIVER/R"]["selected"]
    assert not result["groups"]["DRIVER/S"]["selected"]
    changed = json.loads(json.dumps(document))
    for row in changed["fantasy"]["8"]:
        row["GamedayPoints"] = 10000
    later = fantasy_model._fit(json.dumps(changed), assets, False)
    assert [r for r in result["folds"] if r["round"] < 8] == [
        r for r in later["folds"] if r["round"] < 8
    ]


def test_source_excludes_target_records_labels_and_telemetry(monkeypatch):
    assets, document = scenario(monkeypatch)
    cutoff = public_history.date(document["racing"][-1]["end"])
    document["features"] = [dict(completed_at=cutoff.isoformat(), secret="future")]
    monkeypatch.setattr(public_history, "current", lambda: dict(document=document))
    source = fantasy_model._source(assets, cutoff)
    data = json.loads(source)
    assert len(data["fantasy"]) == 7
    assert all(public_history.date(r["end"]) < cutoff for r in data["racing"])
    document["features"][0]["secret"] = "changed"
    assert fantasy_model._source(assets, cutoff) == source
    document["features"].append(
        dict(completed_at=(cutoff - timedelta(days=1)).isoformat(), value=1)
    )
    assert fantasy_model._source(assets, cutoff) != source


def test_missing_sprint_points_do_not_become_zero_race_training_labels(monkeypatch):
    assets, document = scenario(monkeypatch)
    document["racing"][-1]["sessions"]["S"] = []
    result = fantasy_model._fit(json.dumps(document), assets, False)
    assert any(row["round"] == 8 and row["session"] == "Q" for row in result["folds"])
    assert not any(
        row["round"] == 8 and row["session"] == "R" for row in result["folds"]
    )


def test_enriched_results_supply_the_same_fantasy_proxy_without_raw_reload(monkeypatch):
    session = [
        dict(tla="AAA", position=2, grid=5, classified=True),
        dict(tla="BBB", position=20, grid=1, classified=False),
    ]
    monkeypatch.setattr(
        public_history,
        "current",
        lambda: dict(
            document=dict(
                racing=[
                    dict(
                        season=2026,
                        round=1,
                        sessions={"Q": session, "R": session, "S": session},
                    )
                ]
            )
        ),
    )
    assert projections._session_scores(2026, 1, "Q") == dict(AAA=9.0, BBB=0.0)
    assert projections._session_scores(2026, 1, "R") == dict(AAA=21.0, BBB=-20.0)
    assert projections._session_scores(2026, 1, "S") == dict(AAA=10.0, BBB=-10.0)


def test_ridge_constant_features_stay_finite_and_non_sprint_stays_zero(monkeypatch):
    train = [dict(x=[0.0, 0.0], y=10.0, event=i) for i in range(5)]
    assert fantasy_model._predict(train, [[0.0, 0.0]], (2.0, 10.0))[0] == pytest.approx(
        10.0
    )
    assets = (Asset("d", "Driver", "DRIVER", "t", 50, "DRV"),)
    weekend = Weekend(
        2026, 20, "Race", 20, datetime(2026, 11, 1, tzinfo=timezone.utc), False, False
    )
    baseline = {(0, "d"): projections.Estimate(2, 0, 3)}
    monkeypatch.setattr(public_history, "current", lambda: None)
    assert fantasy_model.forecast(assets, [weekend], baseline) == baseline


def test_joint_qualifying_features_measure_both_car_q3_not_mean_threshold(monkeypatch):
    assets = (
        Asset("a", "A", "DRIVER", "t", 50, "AAA"),
        Asset("b", "B", "DRIVER", "t", 50, "BBB"),
        Asset("t", "Team", "CONSTRUCTOR", "t", 50),
    )
    ranks = np.array([[1, 11], [11, 1], [1, 2], [2, 1]])
    draw = dict(ranks=ranks, classified=np.ones_like(ranks, dtype=bool))
    monkeypatch.setattr(
        racing_model, "draw", lambda *args, **kwargs: dict(Q=draw, R=draw)
    )
    weekend = Weekend(
        2026, 20, "Race", 20, datetime(2026, 11, 1, tzinfo=timezone.utc), False, False
    )
    rows = fantasy_model._features(assets, weekend, [], [], {}, False, 1)
    assert rows["t", "Q"][4] == pytest.approx(0.5)
    assert rows["t", "Q"][5] == pytest.approx(1.0)
