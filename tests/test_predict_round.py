"""Shared-draw outcomes for the historical Predict question families."""

from copy import deepcopy
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from f1fantasy import (
    predict_evidence as evidence,
    predict_model as model,
)
from f1fantasy import predict
from test_predict_model import question, literals


@pytest.fixture
def grid(monkeypatch):
    monkeypatch.setattr(
        model, "_now", lambda: datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    names = ["Williams", "Aston Martin", "Racing Bulls"] + [
        f"Team {i}" for i in range(3, 11)
    ]
    drivers = [
        {
            "id": str(i),
            "name": f"Driver {i}",
            "kind": 1,
            "tla": f"D{i}",
            "team_id": str(i // 2),
            "team_name": names[i // 2],
        }
        for i in range(22)
    ]
    teams = [
        {"id": f"t{i}", "team_id": str(i), "kind": 2, "name": name}
        for i, name in enumerate(names)
    ]
    snapshot = {
        "season": 2026,
        "gameday_id": 1,
        "scope": "round",
        "first_session_utc": "2026-10-01T12:00:00Z",
        "roster": drivers + teams,
        "_sprint": True,
    }
    draws = {
        kind: {
            "ranks": np.tile(np.arange(1, 23), (3, 1)),
            "classified": np.ones((3, 22), dtype=bool),
        }
        for kind in ("Q", "SQ", "R", "S")
    }
    return snapshot, drivers, teams, draws


def run(grid, text, options=None, template=4, records=()):
    snapshot, drivers, _, draws = grid
    return model._question(
        question(1, text, options or literals("Yes", "No"), template),
        snapshot,
        drivers,
        draws,
        records,
    )


@pytest.mark.parametrize(
    "text,both,stage",
    [
        ("Will both Williams cars get out of Q1?", True, 2),
        ("Will both Racing Bulls cars get out of Q1?", True, 2),
        ("Will Aston Martin get a car into Q2?", False, 2),
        ("Will Williams get both cars into Q3?", True, 3),
        ("Will both Aston Martins progress beyond Q1?", True, 2),
    ],
)
def test_named_team_progression_and_nonqualification(grid, text, both, stage):
    snapshot, drivers, _, draws = grid
    selected = [
        i
        for i, d in enumerate(drivers)
        if d["team_id"] in model._mentioned_teams(model._text(text), snapshot["roster"])
    ]
    assert len(selected) == 2
    draws["Q"]["classified"][1, selected[0]] = False
    draws["Q"]["classified"][2, selected] = False
    result = run(grid, text)
    assert result["probabilities"] == {
        "100": pytest.approx(1 / 3 if both else 2 / 3),
        "101": pytest.approx(2 / 3 if both else 1 / 3),
    }


def test_team_q3_count_uses_distinct_teams_and_sprint_qualifying(grid):
    _, _, _, draws = grid
    draws["SQ"]["ranks"][:, [1, 10]] = draws["SQ"]["ranks"][:, [10, 1]]
    options = literals("5", "6", "7", "8", "9", "10")
    assert (
        run(grid, "How many teams will get a driver into Q3?", options, 6)[
            "probabilities"
        ]["100"]
        == 1
    )
    assert (
        run(grid, "How many teams will get a car into Sprint Q3?", options, 6)[
            "probabilities"
        ]["101"]
        == 1
    )


def test_sprint_point_teams_count_only_top_eight_classified(grid):
    _, _, _, draws = grid
    draws["S"]["classified"][:, :2] = False
    result = run(
        grid, "How many teams scores points in The Sprint?", literals("3", "4", "5"), 6
    )
    assert result["probabilities"] == {"100": 1, "101": 0, "102": 0}


def test_constructor_comparisons_include_sprint_and_no_points_for_ties(grid):
    snapshot, drivers, teams, draws = grid
    race = np.array([1, 22, 2, 3] + list(range(4, 22)))
    sprint = np.array([1, 2, 9, 10, 3, 4, 5, 6, 7, 8] + list(range(11, 23)))
    draws["R"]["ranks"][:] = race
    draws["S"]["ranks"][:] = sprint
    result = run(
        grid,
        "Which of these teams will score the most points over the weekend?",
        teams[:2],
        7,
    )
    assert result["probabilities"] == {"t0": 1, "t1": 0}
    snapshot["_sprint"] = False
    assert run(grid, "Which of these teams will score the most points?", teams[:2], 7)[
        "probabilities"
    ] == {"t0": 0, "t1": 1}
    assert run(
        grid, "Which team scores the highest race finishing position?", teams[:2], 7
    )["probabilities"] == {"t0": 1, "t1": 0}
    draws["R"]["classified"][:, :4] = False
    tied = run(grid, "Which of these teams will score the most points?", teams[:2], 7)
    assert tied["probabilities"] == {"t0": 0, "t1": 0}
    assert tied["evidence"]["tie_probability"] == 1


def test_constructor_literal_options_include_an_explicit_tied_answer(grid):
    snapshot, _, _, draws = grid
    snapshot["_sprint"] = False
    options = literals("Williams", "Aston Martin", "Tied")
    # Literal option IDs are unrelated to the constructor roster IDs.
    options[0]["id"], options[1]["id"] = "t1", "t0"
    result = run(grid, "Which of these teams will score the most points?", options, 3)
    assert result["probabilities"] == {"t1": 1, "t0": 0, "102": 0}
    draws["R"]["classified"][:, :4] = False
    result = run(grid, "Which of these teams will score the most points?", options, 3)
    assert result["probabilities"] == {"t1": 0, "t0": 0, "102": 1}
    assert result["evidence"]["tie_policy"] == "Explicit tied answer"


def test_maximum_gain_uses_shared_grid_and_only_classified_finishers(grid):
    snapshot, _, _, draws = grid
    draws["R"]["ranks"][:, [0, 8]] = draws["R"]["ranks"][:, [8, 0]]
    assert (
        run(
            grid,
            "Most positions gained by a driver in the race?",
            literals("<6", "8", ">8"),
            6,
        )["probabilities"]["101"]
        == 1
    )
    draws["R"]["classified"][:, 8] = False
    assert (
        run(
            grid,
            "Most positions gained by a driver in the race?",
            literals("0", "8"),
            6,
        )["probabilities"]["100"]
        == 1
    )
    snapshot["starting_grid"] = {f"D{i}": 22 - i for i in range(22)}
    assert (
        run(
            grid,
            "Most positions gained by a driver in the race?",
            literals("<14", "14", ">14"),
            6,
        )["probabilities"]["102"]
        == 1
    )


def standings_record(drivers):
    return {
        "season": 2026,
        "round": 1,
        "end": "2026-09-01T18:00:00Z",
        "sessions": {
            "R": [
                {
                    "tla": d["tla"],
                    "team_name": d["team_name"],
                    "position": i + 1,
                    "classified": True,
                    "points": 0,
                }
                for i, d in enumerate(drivers)
            ]
        },
    }


def test_driver_and_team_championship_use_prior_points_actual_teams_and_countback(grid):
    snapshot, drivers, teams, draws = grid
    record = standings_record(drivers)
    record["sessions"]["R"][1]["points"] = 100
    assert (
        run(
            grid,
            "Who leads the Drivers' Championship after the Grand Prix?",
            drivers[:4],
            4,
            [record],
        )["probabilities"]["1"]
        == 1
    )
    # The driver's previous points belong to their historical constructor.
    record["sessions"]["R"][1]["team_name"] = "Aston Martin"
    assert run(
        grid,
        "Who's ahead in the Teams' Championship after the Grand Prix?",
        teams[:2],
        7,
        [record],
    )["probabilities"] == {"t0": 0, "t1": 1}
    record["sessions"]["R"][1]["points"] = None
    assert (
        "incomplete"
        in run(
            grid,
            "Who leads the Drivers' Championship after the Grand Prix?",
            drivers[:4],
            4,
            [record],
        )["unsupported"]
    )


def test_replaced_driver_retains_points_and_countback_but_earns_no_new_points(grid):
    _, drivers, teams, _ = grid
    record = standings_record(drivers)
    record["sessions"]["R"].append(
        {
            "tla": "OLD",
            "team_name": "Aston Martin",
            "points": 40,
            "position": None,
            "classified": False,
        }
    )
    leader = run(
        grid,
        "Who leads the Drivers' Championship after the Grand Prix?",
        drivers[:4],
        4,
        [record],
    )
    assert sum(leader["probabilities"].values()) == 0  # Former driver still leads.
    second = run(
        grid,
        "Who leaves second in the Championship standings?",
        drivers[:4],
        4,
        [record],
    )
    assert second["probabilities"]["0"] == 1
    constructors = run(
        grid,
        "Who's ahead in the Teams' Championship after the Grand Prix?",
        teams[:2],
        7,
        [record],
    )
    assert constructors["probabilities"] == {"t0": 0, "t1": 1}


def test_title_clinching_counts_remaining_sprints_and_does_not_reannounce_title(grid):
    snapshot, drivers, _, draws = grid
    snapshot["_sprint"] = False
    snapshot["season_fixtures"] = []
    for day, date, kind in [(1, "2026-10-01", "Race"), (2, "2026-10-10", "Race")]:
        snapshot["season_fixtures"].append(
            {
                "GamedayId": day,
                "Season": 2026,
                "IsBonusRound": 0,
                "IsPostponed": 0,
                "MeetingName": f"Grand Prix {day}",
                "SessionType": kind,
                "SessionStartDateISO8601": date + "T12:00:00Z",
                "SessionEndDateISO8601": date + "T14:00:00Z",
            }
        )
    record = standings_record(drivers)
    record["sessions"]["R"][0]["points"] = 45
    yes = run(
        grid,
        "Will a new F1 Drivers' Champion be crowned this weekend?",
        records=[record],
    )
    assert yes["probabilities"] == {"100": 1, "101": 0}
    sprint = deepcopy(snapshot["season_fixtures"][-1])
    sprint["SessionType"] = "Sprint"
    sprint["SessionStartDateISO8601"] = "2026-10-09T12:00:00Z"
    snapshot["season_fixtures"].append(sprint)
    # 45 + 25 - 18 = 52 still exceeds 33, so adjust to test the exact boundary.
    record["sessions"]["R"][0]["points"] = 22
    assert run(
        grid,
        "Will a new F1 Drivers' Champion be crowned this weekend?",
        records=[record],
    )["probabilities"] == {"100": 0, "101": 1}
    snapshot["season_fixtures"].pop()
    assert run(
        grid,
        "Will a new F1 Drivers' Champion be crowned this weekend?",
        records=[record],
    )["probabilities"] == {"100": 1, "101": 0}
    record["sessions"]["R"][0]["points"] = 200
    assert run(
        grid,
        "Will a new F1 Drivers' Champion be crowned this weekend?",
        records=[record],
    )["probabilities"] == {"100": 0, "101": 1}


def test_sporting_nationality_is_sourced_not_inferred_from_birthplace(
    grid, monkeypatch
):
    _, drivers, _, draws = grid
    facts = {
        "source": evidence.JOLPICA,
        "drivers": [
            {
                "name": d["name"],
                "tla": d["tla"],
                "nationality": "British" if i in (0, 11) else "Thai",
            }
            for i, d in enumerate(drivers)
        ],
    }
    monkeypatch.setattr(evidence, "document", lambda: {"predict_facts": facts})
    assert (
        run(
            grid,
            "How many British drivers score points in the Grand Prix on Sunday?",
            literals("0", "1", "2"),
            6,
        )["probabilities"]["101"]
        == 1
    )
    assert (
        run(grid, "Will a British driver win the Grand Prix on Sunday?")[
            "probabilities"
        ]["100"]
        == 1
    )
    draws["S"]["ranks"][:, [0, 9]] = draws["S"]["ranks"][:, [9, 0]]
    assert (
        run(
            grid,
            "How many British drivers score points in the Sprint?",
            literals("0", "1", "2"),
            6,
        )["probabilities"]["100"]
        == 1
    )
    assert (
        run(grid, "Will a British driver win the Sprint?")["probabilities"]["101"] == 1
    )
    facts["drivers"].pop()
    assert (
        "nationality"
        in run(grid, "Will a British driver win the Grand Prix on Sunday?")[
            "unsupported"
        ]
    )


def test_new_venue_winner_uses_complete_career_history_and_excludes_future(
    grid, monkeypatch
):
    _, drivers, _, draws = grid
    facts = {
        "source": evidence.JOLPICA,
        "winner_history_complete": True,
        "winners": [
            {
                "meeting": "Belgian Grand Prix",
                "end": "2020-09-01T12:00:00Z",
                "driver_name": "Driver 0",
                "tla": "D0",
            },
            {
                "meeting": "Hungarian Grand Prix",
                "end": "2027-09-01T12:00:00Z",
                "driver_name": "Driver 0",
                "tla": "D0",
            },
            {
                "meeting": "Hungarian Grand Prix",
                "end": "2020-09-01T12:00:00Z",
                "driver_name": "Older Winner",
                "tla": "OLD",
            },
        ],
    }
    monkeypatch.setattr(evidence, "document", lambda: {"predict_facts": facts})
    assert (
        run(grid, "Will we see a new Belgian Grand Prix winner?")["probabilities"][
            "101"
        ]
        == 1
    )
    assert (
        run(grid, "Will we see a new Hungarian Grand Prix winner?")["probabilities"][
            "100"
        ]
        == 1
    )
    facts["winner_history_complete"] = False
    assert (
        "complete sourced"
        in run(grid, "Will we see a new Belgian Grand Prix winner?")["unsupported"]
    )


def test_race_control_observations_distinguish_deployment_ending_and_repeated_flags():
    class Session:
        race_control_messages = pd.DataFrame(
            [
                {"Message": "VIRTUAL SAFETY CAR DEPLOYED", "Lap": 2},
                {"Message": "VIRTUAL SAFETY CAR DEPLOYED", "Lap": 2},
                {"Message": "VIRTUAL SAFETY CAR ENDING", "Lap": 3},
                {"Message": "GREEN LIGHT", "Flag": "GREEN", "Scope": "Track", "Lap": 3},
                {"Message": "SAFETY CAR DEPLOYED", "Lap": 12},
                {"Message": "SAFETY CAR IN THIS LAP", "Lap": 15},
                {"Flag": "RED", "Scope": "Track", "Lap": 16},
                {"Flag": "RED", "Scope": "Track", "Lap": 16},
                {"Flag": "GREEN", "Scope": "Track", "Lap": 16},
                {"Flag": "RED", "Scope": "Track", "Lap": 20},
            ]
        )
        results = pd.DataFrame({"Laps": [30, 0, 29]})

    assert evidence.race_observation(Session()) == {
        "safety_laps": [2, 12],
        "red_flags": 2,
        "all_complete_first_lap": False,
    }


def test_race_control_probabilities_cutoff_windows_missing_data_and_seed(
    grid, monkeypatch
):
    snapshot, drivers, _, _ = grid
    draws = {
        k: {
            "ranks": np.tile(v["ranks"][0], (4000, 1)),
            "classified": np.tile(v["classified"][0], (4000, 1)),
        }
        for k, v in grid[3].items()
    }
    grid = snapshot, drivers, grid[2], draws
    rows = [
        {
            "season": 2025,
            "round": i + 1,
            "end": "2025-10-01T12:00:00Z",
            "safety_laps": [12],
            "red_flags": 0,
            "all_complete_first_lap": True,
        }
        for i in range(8)
    ]
    monkeypatch.setattr(evidence, "document", lambda: {"predict_races": rows})
    early = run(
        grid,
        "Will the Safety Car or VSC be required during the first 5 laps of the Grand Prix?",
    )
    whole = run(grid, "Will there be a Safety Car or VSC during the GP?")
    assert early["probabilities"]["100"] < 0.1
    assert whole["probabilities"]["100"] > 0.9
    assert sum(whole["probabilities"].values()) == pytest.approx(1)
    baseline = deepcopy(whole)
    rows.append({**rows[0], "end": "2027-01-01T12:00:00Z", "safety_laps": []})
    assert run(grid, "Will there be a Safety Car or VSC during the GP?") == baseline
    for text in (
        "How many times will the red flag be used during Sunday's race?",
        "How many times will the Safety Car or VSC be required during the Grand Prix?",
    ):
        result = run(grid, text, literals("0", "1", "2", ">2"), 6)
        assert sum(result["probabilities"].values()) == pytest.approx(1)
    assert (
        run(grid, "Will we see all 22 cars complete the first lap of the race?")[
            "probabilities"
        ]["100"]
        > 0.9
    )
    rows.clear()
    assert (
        "observations unavailable"
        in run(grid, "Will there be a Safety Car or VSC during the GP?")["unsupported"]
    )


def test_preseason_pitstop_uses_stationary_times_and_filters_post_cutoff(
    grid, monkeypatch
):
    snapshot, _, teams, _ = grid
    snapshot.update(
        questions=[
            question(1, "Which team will set the fastest pitstop time?", teams[:2], 2)
        ],
        season_fixtures=[],
    )
    events = [
        {
            "season": 2025,
            "round": i,
            "end": "2025-10-01T18:00:00Z",
            "stops": [
                {
                    "team_name": t["name"],
                    "seconds": 2 + j,
                    "date": "2025-10-01T12:00:00Z",
                }
                for j, t in enumerate(teams[:2])
            ],
        }
        for i in range(4)
    ]
    monkeypatch.setattr(evidence, "document", lambda: {"stationary_stops": events})
    forecast = predict.pitstop_forecasts(snapshot)[1]
    assert "stationary-lognormal" in forecast["model_type"]
    assert forecast["probabilities"]["t0"] > forecast["probabilities"]["t1"]
    events[-1]["stops"][0]["date"] = "2027-01-01T12:00:00Z"
    assert "unsupported" in predict.pitstop_forecasts(snapshot)[1]
