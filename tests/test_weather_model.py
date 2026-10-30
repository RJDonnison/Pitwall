from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from f1fantasy import weather_model
from f1fantasy.data import Asset, Weekend

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
ASSET = Asset("1", "Driver", "DRIVER", "a", 100)
WEEKEND = Weekend(2026, 20, "Test", 20, NOW + timedelta(days=2), False, False)
WEATHER = dict(
    status="available", fetched_at=NOW.isoformat(), daily_rain_probability_max=80
)


def history():
    d = dict(racing=[], fantasy={}, fantasy_events={})
    for n in range(6):
        end = (NOW - timedelta(days=10 - n)).isoformat()
        wet = n < 3
        d["racing"].append(
            dict(
                end=end,
                sessions={"Q": [], "R": []},
                session_context={
                    k: {"regime": "wet" if wet else "dry"} for k in ("Q", "R")
                },
            )
        )
        d["fantasy_events"][str(n)] = end
        d["fantasy"][str(n)] = [
            dict(
                PlayerId=1,
                QualifyingPoints=30 if wet else 10,
                GamedayPoints=90 if wet else 30,
            )
        ]
    return d


def test_weather_changes_session_forecasts_with_hand_calculated_shrinkage():
    d = history()
    wet = weather_model.candidate([ASSET], WEEKEND, {"1": [2, 0, 10]}, WEATHER, d, NOW)
    dry = weather_model.candidate(
        [ASSET],
        WEEKEND,
        {"1": [2, 0, 10]},
        {**WEATHER, "daily_rain_probability_max": 10},
        d,
        NOW,
    )
    assert wet["forecasts"]["1"] == pytest.approx([2 + 30 / 11, 0, 10 + 60 / 11])
    assert dry["forecasts"]["1"] == pytest.approx([2 - 30 / 11, 0, 10 - 60 / 11])
    assert wet["baseline_forecasts"]["1"] == [2, 0, 10]
    assert wet["samples"] == {"1/Q": 3, "1/R": 3}


def test_future_finalizations_and_other_formats_cannot_change_weather_adjustments():
    d = history()
    expected = weather_model.candidate(
        [ASSET], WEEKEND, {"1": [2, 0, 10]}, WEATHER, d, NOW
    )
    for n, sprint, end, finalized in (
        (7, True, NOW - timedelta(days=2), NOW - timedelta(days=2)),
        (8, False, NOW + timedelta(days=1), NOW + timedelta(days=1)),
        (9, False, NOW - timedelta(hours=1), NOW + timedelta(hours=1)),
    ):
        d["racing"].append(
            dict(
                end=end.isoformat(),
                sessions={"Q": [], "R": [], **({"S": []} if sprint else {})},
                session_context={k: {"regime": "wet"} for k in ("Q", "R")},
            )
        )
        d["fantasy_events"][str(n)] = finalized.isoformat()
        d["fantasy"][str(n)] = [
            dict(
                PlayerId=1,
                QualifyingPoints=100000,
                SprintPoints=99999,
                GamedayPoints=999999,
            )
        ]
    assert (
        weather_model.candidate([ASSET], WEEKEND, {"1": [2, 0, 10]}, WEATHER, d, NOW)
        == expected
    )


def test_forward_weather_mae_uses_frozen_weather_free_pairs_and_separate_populations():
    row = dict(
        sprint=False,
        assets=[dict(id="d", kind="DRIVER"), dict(id="c", kind="CONSTRUCTOR")],
        forecasts={"d": [10, 0, 20], "c": [50, 0, 80]},
        actual={"d": [12, 0, 25], "c": [70, 0, 100]},
        weather_model=dict(
            model=weather_model.VERSION,
            status="selected",
            forecasts={"d": [10, 0, 20], "c": [50, 0, 80]},
            baseline_forecasts={"d": [5, 0, 10], "c": [40, 0, 60]},
        ),
    )
    groups = weather_model.evaluation([row])["groups"]
    driver = next(
        g
        for g in groups
        if g["kind"] == "DRIVER" and g["session"] == "R" and not g["sprint"]
    )
    team = next(
        g
        for g in groups
        if g["kind"] == "CONSTRUCTOR" and g["session"] == "R" and not g["sprint"]
    )
    assert (driver["candidate_mae"], driver["baseline_mae"]) == (5, 15)
    assert (team["candidate_mae"], team["baseline_mae"]) == (20, 40)
    other = deepcopy(row)
    other["weather_model"]["model"] = "older-weather-model"
    assert all(g["weekends"] == 0 for g in weather_model.evaluation([other])["groups"])
    row["model"] = {"weather": weather_model.VERSION, "telemetry": True}
    assert all(
        g["weekends"] == 0
        for g in weather_model.evaluation(
            [row], {"weather": weather_model.VERSION, "telemetry": False}
        )["groups"]
    )


def test_missing_sprint_scores_cannot_enter_race_analogue_as_zero():
    d = history()
    for record in d["racing"]:
        record["sessions"]["S"] = []
    sprint = Weekend(2026, 20, "Sprint test", 20, NOW + timedelta(days=2), True, False)
    result = weather_model.candidate(
        [ASSET], sprint, {"1": [2, 5, 10]}, WEATHER, d, NOW
    )
    assert result["samples"]["1/R"] == 0
    assert result["samples"]["1/S"] == 0
    assert result["forecasts"]["1"][1:] == [5, 10]
