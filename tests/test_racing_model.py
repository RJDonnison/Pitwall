from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from f1fantasy import racing_data, racing_model, pitstop_model


def history(count=12):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(count):
        rows = [
            {
                "tla": str(j),
                "position": j + 1,
                "team_name": "A" if j < 2 else "B",
                "classified": True,
                "qualified": True,
                "status": "Finished",
                "pace_gap_pct": float(j // 2) + (i % 2) * 0.01,
                "points": 25 - j,
            }
            for j in range(4)
        ]
        records.append(
            {
                "season": 2026,
                "round": i + 1,
                "race_start_utc": (start + timedelta(days=7 * i)).isoformat(),
                "end": (start + timedelta(days=7 * i, hours=6)).isoformat(),
                "sessions": {"Q": deepcopy(rows), "R": rows},
                "session_context": {"R": {"regime": "dry"}},
            }
        )
    return records


def test_joint_margin_draws_are_permutations_and_share_car_variation():
    records = history()
    for rec in records:
        for rows in rec["sessions"].values():
            for r in rows:
                r["pace_gap_pct"] = 0
    drivers = racing_model.roster(records[-1])
    params = {**racing_model.PARAMETERS[0], "team_share": 0.9}
    draws = racing_model.draw(
        records, drivers, 5000, np.random.default_rng(7), {}, params
    )
    assert np.all(np.sort(draws["R"]["ranks"], axis=1) == np.arange(1, 5))
    assert np.corrcoef(draws["R"]["ranks"][:, :2].T)[0, 1] > 0


def test_chronological_tuning_never_trains_on_the_scored_target(monkeypatch):
    records = history()
    original = racing_model.draw
    seen = []

    def checked(previous, drivers, *args):
        target = records[len(previous)]
        assert all(r["end"] < target["race_start_utc"] for r in previous)
        assert not any("position" in d or "pace_gap_pct" in d for d in drivers)
        seen.append(len(previous))
        return original(previous, drivers, *args)

    monkeypatch.setattr(racing_model, "draw", checked)
    report = racing_model.evaluate(records, simulations=100)
    assert min(seen) == 8
    assert [f["parameter_training_folds"] for f in report["folds"]] == [0, 1, 2, 3]
    assert report["selected"] == "rank_v1"  # insufficient validation folds
    assert set(report["metrics"]) == {"candidate", "rank_v1", "uniform", "last8"}


def test_driver_changes_car_without_carrying_old_team_absolute_pace():
    records = history()
    drivers = racing_model.roster(records[-1])
    drivers[2]["team_id"] = drivers[2]["team_name"] = "A"
    means, _, _ = racing_model._form(records, drivers, "R", racing_model.PARAMETERS[0])
    assert abs(means[2] - means[0]) < 0.01


@pytest.mark.parametrize(
    "status,expected",
    [
        ("Engine", "mechanical"),
        ("Collision damage", "collision"),
        ("Spun off", "driver_error"),
        ("Disqualified", "disqualified"),
        ("Did not start", "did_not_start"),
        ("+1 Lap", None),
    ],
)
def test_failure_causes_remain_distinct(status, expected):
    assert racing_data.cause(status) == expected


def test_clean_lap_margins_exclude_pit_yellow_deleted_and_wrong_compounds():
    rows = []
    for lap in range(2, 6):
        for driver, time in (("A", 60), ("B", 61), ("C", 62)):
            rows.append(
                dict(
                    Driver=driver,
                    LapNumber=lap,
                    LapTime=pd.Timedelta(seconds=time),
                    IsAccurate=True,
                    PitInTime=pd.NaT,
                    PitOutTime=pd.NaT,
                    TrackStatus="1",
                    Deleted=False,
                    Compound="MEDIUM",
                    TyreLife=lap,
                )
            )
    rows.append({**rows[0], "LapTime": pd.Timedelta(seconds=10), "Deleted": True})
    results = pd.DataFrame(
        [
            dict(
                Abbreviation=d,
                Position=i + 1,
                ClassifiedPosition=str(i + 1),
                Points=0,
                TeamName="Team",
                Status="Finished",
                Laps=5,
                Q1=pd.Timedelta(seconds=60 + i),
            )
            for i, d in enumerate("ABC")
        ]
    )
    session = SimpleNamespace(
        results=results,
        laps=pd.DataFrame(rows),
        weather_data=pd.DataFrame({"Rainfall": [False]}),
    )
    extracted, context = racing_data.extract(session, "R")
    assert extracted[0]["pace_samples"] == 4
    assert extracted[0]["pace_gap_pct"] == pytest.approx(100 * (60 / 61 - 1))
    assert extracted[0]["best_lap_seconds"] == 60
    assert context["regime"] == "dry"


def test_stationary_minimum_uses_service_time_and_opportunity_counts():
    events = [
        {
            "stops": [
                {"team_name": t, "seconds": s}
                for t, s in (("A", 2.0), ("A", 2.1), ("B", 3.0), ("B", 3.1))
            ]
        }
        for _ in range(12)
    ]
    p = pitstop_model.simulate(events, ["A", "B"], str, simulations=3000, prior=1)
    assert p["A"] > 0.95
    assert sum(p.values()) == pytest.approx(1)


def retiring_history(count=12):
    """Team B's cars retire in most races with the generic status 'Retired'."""
    records = history(count)
    for rec in records:
        for row in rec["sessions"]["R"]:
            if row["team_name"] == "B":
                row["classified"] = False
                row["status"] = "Retired"
    return records


def test_retirement_propensity_follows_team_history_and_pools_toward_field():
    records = retiring_history()
    drivers = racing_model.roster(records[-1])
    team_ids = sorted({str(d["team_id"]) for d in drivers})
    teams = {d["team_id"]: d["team_name"] for d in drivers}
    rates = racing_model._retirement_propensity(records, "R", team_ids, teams, drivers)
    by_team = dict(zip(team_ids, rates))
    # Pooling toward the field keeps both rates away from 0 and 1.
    assert by_team["B"] > 2.5 * by_team["A"]
    assert (rates > 0).all() and (rates < 1).all()
    # Without any history every team takes the same (field) rate.
    fresh = racing_model._retirement_propensity([], "R", team_ids, teams, drivers)
    assert np.allclose(fresh, fresh[0])


def test_incident_assignment_is_weighted_by_team_but_keeps_shared_count():
    records = retiring_history()
    drivers = racing_model.roster(records[-1])
    draws = racing_model.draw(
        records, drivers, 4000, np.random.default_rng(3), {}, racing_model.PARAMETERS[0]
    )
    nc = ~draws["R"]["classified"]
    team_b = [i for i, d in enumerate(drivers) if d["team_name"] == "B"]
    team_a = [i for i, d in enumerate(drivers) if d["team_name"] == "A"]
    assert nc[:, team_b].mean() > nc[:, team_a].mean() + 0.2
    # The sampled event count is shared: two of four cars retired in every race.
    assert abs(nc.sum(axis=1).mean() - 2.0) < 0.15


def test_uniform_history_keeps_not_classified_flat_across_teams():
    records = history()
    for rec in records:
        for i, row in enumerate(rec["sessions"]["R"]):
            row["classified"] = (rec["round"] + i) % 4 != 0
            row["status"] = "Finished" if row["classified"] else "Retired"
    drivers = racing_model.roster(records[-1])
    draws = racing_model.draw(
        records, drivers, 6000, np.random.default_rng(5), {}, racing_model.PARAMETERS[0]
    )
    rates = (~draws["R"]["classified"]).mean(axis=0)
    assert rates.max() - rates.min() < 0.08
