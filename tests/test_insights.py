"""Cutoff-safe race statistics and joint FIA championship projections."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from f1fantasy import insights
from f1fantasy.data import Asset, Weekend


@pytest.fixture
def scenario(monkeypatch):
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assets = tuple(
        Asset(str(i), name, "DRIVER", team, 100, tla)
        for i, name, tla, team in [
            (1, "Alpha", "AAA", "a"),
            (2, "Beta", "BBB", "a"),
            (3, "Gamma", "CCC", "b"),
        ]
    ) + (
        Asset("a", "Team A", "CONSTRUCTOR", "a", 100),
        Asset("b", "Team B", "CONSTRUCTOR", "b", 100),
    )
    rows = [
        {
            "tla": tla,
            "team_name": team,
            "position": i + 1,
            "classified": True,
            "qualified": True,
            "points": score,
        }
        for i, (tla, team, score) in enumerate(
            [
                ("AAA", "Team A", 25),
                ("BBB", "Team A", 18),
                ("CCC", "Team B", 15),
                ("OLD", "Former Team", 7),
            ]
        )
    ]
    record = {
        "season": 2026,
        "round": 1,
        "end": (cutoff - timedelta(days=2)).isoformat(),
        "sessions": {"R": rows, "Q": [{**r, "points": None} for r in rows]},
    }
    doc = {
        "racing": [record],
        "events": {
            "2026/1": {
                "RoundNumber": 1,
                "race_start": (cutoff - timedelta(days=3)).isoformat(),
                "EventFormat": "conventional",
            }
        },
    }
    weekends = [
        Weekend(2026, 2, "Example", 2, cutoff + timedelta(days=1), False, False),
        Weekend(2026, 3, "Sprint", 3, cutoff + timedelta(days=8), True, False),
    ]
    ranks = np.array([[1, 2, 3], [2, 1, 3], [1, 3, 2], [3, 2, 1]])
    classified = np.ones_like(ranks, dtype=bool)
    classified[0, 2] = False
    monkeypatch.setattr(
        insights.predict_model,
        "_draw",
        lambda *a: {
            k: {"ranks": ranks, "classified": classified} for k in ("Q", "R", "S")
        },
    )
    return assets, weekends, cutoff, doc


def build(scenario):
    assets, weekends, cutoff, doc = scenario
    return insights._build(doc, assets, weekends, cutoff, False, 4, 42)


def test_joint_projection_preserves_inactive_points_and_sprint_scoring(scenario):
    result = build(scenario)
    champ = result["championship"]
    assert champ["status"] == "ready"
    old = next(r for r in champ["drivers"] if r["key"] == "OLD")
    assert old["observed"] == old["projected"] == 7
    assert old["remaining"] == 0 and old["interval80"] == [7, 7]
    assert old["max_final"] == 7 and not old["title_eligible"]
    assert next(r for r in champ["drivers"] if r["key"] == "AAA")["max_remaining"] == 58
    a = next(r for r in champ["constructors"] if r["asset_id"] == "a")
    # Two GP draws plus one Sprint draw, summed per sample before quantiles.
    expected = 43 + np.array(
        [
            2 * (25 + 18) + 8 + 7,
            2 * (18 + 25) + 7 + 8,
            2 * (25 + 15) + 8 + 6,
            2 * (15 + 18) + 6 + 7,
        ]
    )
    assert a["projected"] == expected.mean()
    assert a["interval80"] == pytest.approx(np.quantile(expected, [0.1, 0.9]))
    driver_sum = sum(r["projected"] for r in champ["drivers"])
    assert driver_sum == pytest.approx(
        sum(r["projected"] for r in champ["constructors"])
    )
    assert result["calibrated"] is False


def test_team_outcomes_are_any_car_and_sprint_is_format_specific(scenario):
    result = build(scenario)
    regular, sprint = result["rounds"]
    assert regular["constructors"]["a"]["podium"] == 1
    assert sum(regular["drivers"][d]["podium"] for d in ("1", "2")) == 2
    assert regular["drivers"]["3"]["nc"] == 0.25
    assert "sprint_win" not in regular["drivers"]["1"]
    assert "sprint_win" in sprint["drivers"]["1"]
    assert sum(r["win"] for r in regular["drivers"].values()) == 1


def test_future_history_is_excluded_and_incomplete_season_blocks_totals(scenario):
    assets, weekends, cutoff, doc = scenario
    future = deepcopy(doc["racing"][0])
    future.update(round=2, end=cutoff.isoformat())
    doc["racing"].append(future)
    assert len(build(scenario)["historical_events"]) == 1
    doc["events"]["2026/2"] = {
        "RoundNumber": 2,
        "race_start": (cutoff - timedelta(days=1)).isoformat(),
    }
    result = build(scenario)
    assert not result["history"][0]["complete"]
    assert result["championship"]["status"] == "unavailable"
    assert result["history"][0]["drivers"][0]["points"] == 25


def test_missing_championship_points_is_unavailable_not_zero(scenario):
    scenario[3]["racing"][0]["sessions"]["R"][0]["points"] = None
    result = build(scenario)
    assert result["championship"]["status"] == "unavailable"
    assert not next(r for r in result["history"][0]["drivers"] if r["key"] == "AAA")[
        "points_complete"
    ]


def test_pitstop_publication_cutoff_and_unknown_team_are_enforced(scenario):
    assets, _, cutoff, doc = scenario
    label = {
        "season": 2026,
        "gameday_id": 1,
        "team_name": "Team A",
        "published_at": (cutoff - timedelta(hours=1)).isoformat(),
        "completed_at": (cutoff - timedelta(days=1)).isoformat(),
    }
    doc["pitstop_winners"] = [
        label,
        {**label, "gameday_id": 2, "published_at": cutoff.isoformat()},
    ]
    result = insights._pitstops(doc, assets, cutoff, 2026)
    assert result["samples"] == 1
    assert result["probabilities"] == {"a": 2 / 3, "b": 1 / 3}
    doc["pitstop_winners"][0]["team_name"] = "Unverified Team"
    assert insights._pitstops(doc, assets, cutoff, 2026)["status"] == "unavailable"


def test_placement_distributions_separate_unclassified_outcomes(scenario):
    result = build(scenario)
    placements = result["rounds"][0]["placements"]
    assert placements["1"]["R"]["mean"] == 1.75
    assert placements["3"]["R"]["nc"] == 0.25
    for rounds in result["rounds"]:
        for sessions in rounds["placements"].values():
            for session in sessions.values():
                assert sum(session["positions"]) + session["nc"] == pytest.approx(1)
    assert "S" not in placements["1"]
    assert "S" in result["rounds"][1]["placements"]["1"]


def test_telemetry_has_the_same_cutoff_for_all_rounds(scenario, monkeypatch):
    assets, weekends, cutoff, doc = scenario

    def adjust(assets, targets):
        assert all(w.first_session == cutoff for w in targets)
        return {}

    monkeypatch.setattr(insights, "adjustments", adjust)
    insights._build(doc, assets, weekends, cutoff, True, 4, 42)


def test_title_ceiling_includes_sprints_and_constructor_car_count(scenario):
    assets, weekends, _, doc = scenario
    champ = build(scenario)["championship"]
    rows = {r["key"]: r for r in champ["drivers"]}
    rows["AAA"]["observed"] = 100
    rows["BBB"]["observed"] = 41
    rows["CCC"]["observed"] = 42
    insights._title_eligibility(champ, doc["racing"], assets, weekends)
    assert rows["BBB"]["max_final"] == 99
    assert not rows["BBB"]["title_eligible"]
    # Reaching 100 with two GP wins beats the leader's one recorded win.
    assert rows["CCC"]["max_final"] == 100 and rows["CCC"]["title_eligible"]
    teams = {r["asset_id"]: r for r in champ["constructors"]}
    assert teams["a"]["max_remaining"] == 2 * 43 + 15
    assert teams["b"]["max_remaining"] == 2 * 25 + 8
    insights._title_eligibility(
        champ, doc["racing"], assets, [replace(w, sprint=False) for w in weekends]
    )
    assert rows["CCC"]["max_final"] == 92 and not rows["CCC"]["title_eligible"]


def test_equal_points_ceiling_uses_gp_countback_and_preserves_unresolved_ties(scenario):
    assets, weekends, _, doc = scenario
    champ = build(scenario)["championship"]
    rows = {r["key"]: r for r in champ["drivers"]}
    rows["AAA"]["observed"] = 100
    rows["CCC"]["observed"] = 42
    leader = doc["racing"][0]["sessions"]["R"][0]
    # Even two future GP wins cannot beat three existing wins at equal points.
    records = [{**doc["racing"][0], "sessions": {"R": [leader]}}] * 3
    insights._title_eligibility(champ, records, assets, weekends)
    assert not rows["CCC"]["title_eligible"]
    # Exact countback remains unresolved; Sprint wins do not break GP countback.
    insights._title_eligibility(champ, records[:2], assets, weekends)
    assert rows["CCC"]["title_eligible"]
