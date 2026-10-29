from copy import deepcopy
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from f1fantasy import predict_model as model
from f1fantasy.data import DataError, Weekend


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    # Ordinary fixtures predict Oct 30; future-target tests explicitly move now.
    monkeypatch.setattr(
        model, "_now", lambda: datetime(2026, 10, 31, tzinfo=timezone.utc)
    )


def test_preseason_uses_previous_season_form_only(season_snapshot, monkeypatch):
    s = season_snapshot
    s["first_session_utc"] = "2026-01-15T12:00:00Z"
    s["questions"] = [
        question(1, "Who will win the Drivers' Championship?", s["roster"][:4], 2)
    ]
    records = model._history(2026, None)
    prior = deepcopy(records[0])
    prior.update(
        season=2025, end="2025-12-01T12:00:00Z", race_start_utc="2025-12-01T06:00:00Z"
    )
    monkeypatch.setattr(model, "_history", lambda *_: [prior] + records)
    monkeypatch.setattr(model, "_draw", fixed_draw)
    result = model.forecast(s, simulations=10, use_telemetry=False)[1]
    assert result["probabilities"]["0"] == 1
    assert result["evidence"]["simulated_gamedays"] == [101, 102, 103, 104, 900, 950]
    assert {r["season"] for r in result["evidence"]["historical_events"]} == {2025}


def test_missing_constructor_identity_only_blocks_constructor_predicate(
    season_snapshot, monkeypatch
):
    s = season_snapshot
    s["questions"] = [
        question(1, "Who will win the Drivers' Championship?", s["roster"][:4], 2),
        question(
            2, "Which team will win the Constructors' Championship?", s["roster"][4:], 2
        ),
    ]
    records = model._history(2026, None)
    records[0]["sessions"]["R"][0]["team_name"] = "Unmapped historical constructor"
    monkeypatch.setattr(model, "_history", lambda *_: records)
    monkeypatch.setattr(model, "_draw", fixed_draw)
    output = model.forecast(s, simulations=10, use_telemetry=False)
    assert output[1]["probabilities"]["0"] == 1
    assert "constructor attribution" in output[2]["unsupported"]


@pytest.fixture
def snapshot(monkeypatch):
    drivers = [
        {
            "id": str(i),
            "name": name,
            "kind": 1,
            "tla": tla,
            "team_id": str(i // 2),
            "team_name": "Aston Martin" if i < 2 else "Other",
        }
        for i, (name, tla) in enumerate(
            [
                ("Oliver Bearman", "BEA"),
                ("Esteban Ocon", "OCO"),
                ("Sergio Pérez", "PER"),
                ("Max Verstappen", "VER"),
            ]
        )
    ]
    result = {
        "season": 2026,
        "gameday_id": 19,
        "race_id": 7403,
        "scope": "round",
        "first_session_utc": "2026-10-30T12:00:00+00:00",
        "fixtures": [],
        "roster": drivers,
        "questions": [],
    }
    records = []
    for round_ in range(1, 5):
        rows = [
            {
                "tla": d["tla"],
                "position": i + 1,
                "classified": True,
                "qualified": True,
                "points": 25 - i * 5,
            }
            for i, d in enumerate(drivers)
        ]
        records.append(
            {
                "season": 2026,
                "round": round_,
                "end": f"2026-0{round_ + 1}-01T12:00:00+00:00",
                "sessions": {
                    "Q": deepcopy(rows),
                    "R": deepcopy(rows),
                    "S": deepcopy(rows),
                },
                "fastest_lap": "BEA",
            }
        )
    monkeypatch.setattr(model, "_history", lambda *_: deepcopy(records))
    monkeypatch.setattr(
        model, "_target", lambda s, c: Weekend(2026, 19, "Mexico", 19, c, False, False)
    )
    return result


def test_named_team_classified_counts_use_driver_union(snapshot):
    drivers = deepcopy(snapshot["roster"])
    for i, d in enumerate(drivers):
        d["team_name"] = "Haas F1 Team" if i < 2 else "Cadillac"
    drivers += [
        {
            "id": "4",
            "name": "Extra One",
            "kind": 1,
            "tla": "EX1",
            "team_id": "2",
            "team_name": "Other",
        },
        {
            "id": "5",
            "name": "Extra Two",
            "kind": 1,
            "tla": "EX2",
            "team_id": "2",
            "team_name": "Other",
        },
    ]
    s = {**snapshot, "roster": drivers, "_sprint": True}
    draws = {
        kind: {"ranks": np.array([[1, 2, 3, 4, 5, 6]]), "classified": np.array([flags])}
        for kind, flags in (
            ("R", [True, False, True, False, True, True]),
            ("S", [False, False, False, False, True, True]),
        )
    }
    for text, expected, tlas, kind in (
        (
            "How many Haas and Cadillac drivers will be classified at end?",
            "102",
            ["BEA", "OCO", "PER", "VER"],
            "r",
        ),
        (
            "How many Haas drivers will be classified at end?",
            "101",
            ["BEA", "OCO"],
            "r",
        ),
        (
            "How many Haas and Cadillac drivers will be classified at end of the Sprint?",
            "100",
            ["BEA", "OCO", "PER", "VER"],
            "s",
        ),
    ):
        result = model._question(
            question(1, text, literals("0", "1", "2", "3", "4", "5", "6"), 6),
            s,
            drivers,
            draws,
            [],
        )
        assert result["probabilities"][expected] == 1
        assert sum(result["probabilities"].values()) == 1
        assert result["evidence"]["classified_driver_tlas"] == tlas
        assert result["model_type"].endswith(f":{kind}:classified_count:teams")
    whole = model._question(
        question(
            1,
            "How many classified finishers?",
            literals("0", "1", "2", "3", "4", "5", "6"),
            6,
        ),
        s,
        drivers,
        draws,
        [],
    )
    assert whole["probabilities"]["104"] == 1
    assert whole["model_type"].endswith(":r:classified_count:grid")


def test_distinct_sprint_qualifying_and_fastest_lap_forecasts(snapshot, monkeypatch):
    records = model._history(2026, None)
    for record in records:
        record["sessions"]["SQ"] = deepcopy(record["sessions"]["Q"])
        for row in record["sessions"]["SQ"]:
            row["position"] = 5 - row["position"]
        record["sprint_fastest_lap"] = "VER"
    monkeypatch.setattr(model, "_history", lambda *_: records)
    monkeypatch.setattr(
        model, "_target", lambda s, c: Weekend(2026, 19, "Mexico", 19, c, True, False)
    )
    options = snapshot["roster"]
    snapshot["questions"] = [
        question(1, "Who will be fastest in qualifying?", options, 2),
        question(2, "Who will be fastest in Sprint qualifying?", options, 2),
        question(3, "Who will set the fastest lap of the race?", options, 2),
        question(4, "Who will set the fastest lap of the Sprint?", options, 2),
        question(5, "Who qualifies highest for the Grand Prix?", options[:2], 7),
        question(6, "Who qualifies highest in the Sprint Shootout?", options[:2], 7),
    ]
    output = model.forecast(snapshot, simulations=4000, seed=42, use_telemetry=False)
    assert output[1]["probabilities"]["0"] > output[1]["probabilities"]["3"]
    assert output[2]["probabilities"]["3"] > output[2]["probabilities"]["0"]
    assert output[3]["probabilities"]["0"] > output[3]["probabilities"]["3"]
    assert output[4]["probabilities"]["3"] > output[4]["probabilities"]["0"]
    assert output[5]["probabilities"]["0"] > output[5]["probabilities"]["1"]
    assert output[6]["probabilities"]["1"] > output[6]["probabilities"]["0"]
    for id_, suffix in {
        1: "q:pole",
        2: "sq:pole",
        3: "r:fastest_lap",
        4: "s:fastest_lap",
        5: "q:quali_h2h",
        6: "sq:quali_h2h",
    }.items():
        assert output[id_]["model_type"].endswith(":" + suffix)
    assert output == model.forecast(
        snapshot, simulations=4000, seed=42, use_telemetry=False
    )


def test_sprint_fastest_lap_requires_actual_sprint_lap_history(snapshot, monkeypatch):
    monkeypatch.setattr(
        model, "_target", lambda s, c: Weekend(2026, 19, "Mexico", 19, c, True, False)
    )
    snapshot["questions"] = [
        question(1, "Who will set the fastest Sprint lap?", snapshot["roster"], 2)
    ]
    result = model.forecast(snapshot, simulations=100, use_telemetry=False)[1]
    assert "timed laps" in result["unsupported"]


def test_sprint_and_regular_qualifying_stage_categories_are_distinct(snapshot):
    drivers = deepcopy(snapshot["roster"][:2])
    for i in range(2, 22):
        drivers.append(
            {
                "id": str(i),
                "kind": 1,
                "name": f"Driver {i}",
                "tla": f"D{i}",
                "team_id": str(i // 2),
                "team_name": f"Team {i // 2}",
            }
        )
    s = {**snapshot, "roster": drivers, "_sprint": True}
    q = np.arange(1, 23)[None, :]
    sq = q.copy()
    q[:, [0, 1, 10, 11]] = q[:, [10, 11, 0, 1]]
    sq[:, [0, 1, 16, 17]] = sq[:, [16, 17, 0, 1]]
    draws = {
        kind: {"ranks": ranks, "classified": np.ones((1, 22), dtype=bool)}
        for kind, ranks in (("Q", q), ("SQ", sq))
    }
    regular = model._question(
        question(
            1,
            "What is the furthest Aston Martin will progress in qualifying?",
            literals("Q3", "Q2", "Q1"),
        ),
        s,
        drivers,
        draws,
        [],
    )
    sprint = model._question(
        question(
            2,
            "What is the furthest Aston Martin will progress in Sprint qualifying?",
            literals("SQ3", "SQ2", "SQ1"),
        ),
        s,
        drivers,
        draws,
        [],
    )
    assert regular["probabilities"] == {"100": 0, "101": 1, "102": 0}
    assert sprint["probabilities"] == {"100": 0, "101": 0, "102": 1}
    assert regular["model_type"].endswith(":q:team_qstage")
    assert sprint["model_type"].endswith(":sq:team_qstage")


def test_sq_draw_has_shared_pace_but_independent_noise(snapshot):
    records = model._history(2026, None)
    for record in records:
        record["sessions"]["SQ"] = deepcopy(record["sessions"]["Q"])
    draw = model._draw(records, snapshot["roster"], 4000, np.random.default_rng(5), {})
    assert np.mean(draw["Q"]["ranks"] != draw["SQ"]["ranks"]) > 0.3
    # Positive same-driver rank correlation, with identically ordered historical
    # means, comes from the shared performance noise rather than aliasing Q.
    assert np.corrcoef(draw["Q"]["ranks"][:, 0], draw["SQ"]["ranks"][:, 0])[0, 1] > 0.05
    for record in records:
        del record["sessions"]["SQ"]
    assert "SQ" not in model._draw(
        records, snapshot["roster"], 10, np.random.default_rng(5), {}
    )


def test_future_target_freezes_history_and_telemetry_at_current_utc(
    snapshot, monkeypatch
):
    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(model, "_now", lambda: now)
    snapshot["first_session_utc"] = "2026-12-01T12:00:00Z"
    snapshot["questions"] = [
        question(1, "Who will set the fastest lap?", snapshot["roster"], 2)
    ]
    records = model._history(2026, None)
    baseline = model.forecast(snapshot, simulations=100, use_telemetry=False)
    for end in (now.isoformat(), "2026-11-01T12:00:00Z", "2026-11-15T12:00:00Z"):
        future = deepcopy(records[-1])
        future.update(end=end, round=23, fastest_lap="VER")
        records.append(future)
    calls = []

    def history(season, cutoff):
        calls.append(cutoff)
        return records

    def telemetry(assets, weekends):
        assert weekends[0].first_session == now
        return {}

    monkeypatch.setattr(model, "_history", history)
    monkeypatch.setattr(model, "adjustments", telemetry)
    assert model.forecast(snapshot, simulations=100) == baseline
    assert calls == [now]
    assert baseline[1]["evidence"]["cutoff_utc"] == now.isoformat()
    assert (
        baseline[1]["evidence"]["target_first_session_utc"]
        == model._utc(snapshot["first_session_utc"]).isoformat()
    )


@pytest.mark.parametrize(
    "year,event_format,identifier",
    [
        (2023, "sprint_shootout", "SS"),
        (2024, "sprint_qualifying", "SQ"),
        (2026, "sprint_qualifying", "SQ"),
        (2022, "sprint", None),
    ],
)
def test_history_loads_distinct_sq_and_true_sprint_laps(
    monkeypatch, year, event_format, identifier
):
    class Event(dict):
        def get_session_date(self, *_args, **_kwargs):
            return f"{year}-02-01T12:00:00Z"

    class Schedule:
        def __init__(self, events):
            self.events = events

        def iterrows(self):
            return iter(enumerate(self.events))

    event = Event(RoundNumber=1, EventFormat=event_format)
    loaded = []

    class Session:
        def __init__(self, kind):
            self.kind = kind
            self.results = pd.DataFrame(
                [
                    {
                        "Abbreviation": "BEA",
                        "Position": 2 if kind in {"SQ", "SS"} else 1,
                        "ClassifiedPosition": "1",
                        "Points": 25,
                        "Status": "Finished",
                        "TeamName": "Haas",
                    },
                    {
                        "Abbreviation": "OCO",
                        "Position": 1 if kind in {"SQ", "SS"} else 2,
                        "ClassifiedPosition": "2",
                        "Points": 18,
                        "Status": "Finished",
                        "TeamName": "Haas",
                    },
                ]
            )
            self.laps = pd.DataFrame(
                {
                    "Driver": ["BEA", "OCO", "VER"],
                    "LapTime": pd.to_timedelta(
                        [60, 70, 30] if kind == "R" else [70, 60, 30], unit="s"
                    ),
                    "Deleted": [False, False, True],
                    "LapStartDate": [pd.Timestamp(f"{year}-02-01T12:10:00")] * 3,
                }
            )

        def load(self, **kwargs):
            loaded.append((self.kind, kwargs["laps"]))

    monkeypatch.setattr(model, "configure_cache", lambda: None)
    monkeypatch.setattr(
        model.fastf1,
        "get_event_schedule",
        lambda season, **_: Schedule([event] if season == year else []),
    )
    monkeypatch.setattr(
        model.fastf1, "get_session", lambda season, round_, kind: Session(kind)
    )
    (record,) = model._history(year, datetime(year, 10, 1, tzinfo=timezone.utc))
    assert record["fastest_lap"] == "BEA"
    assert record["sprint_fastest_lap"] == "OCO"
    assert ("R", True) in loaded and ("S", True) in loaded
    assert ("Q", False) in loaded
    if identifier:
        assert (identifier, False) in loaded
        assert record["sessions"]["SQ"][0]["position"] == 2
        assert record["sessions"]["Q"][0]["position"] == 1
    else:
        assert "SQ" not in record["sessions"]
        assert not any(kind in {"SQ", "SS"} for kind, _ in loaded)


def question(id_, text, options, template=4):
    return {
        "id": id_,
        "number": id_,
        "text": text,
        "subtext": "",
        "template": template,
        "choice_limit": 3 if template == 1 else 1,
        "status": 2,
        "config": {},
        "options": options,
    }


def literals(*names):
    return [
        {"id": str(i + 100), "name": name, "kind": 3, "points": 10}
        for i, name in enumerate(names)
    ]


def test_current_question_families_and_shared_podium(snapshot):
    options = snapshot["roster"]
    snapshot["questions"] = [
        question(1, "Predict the podium for the Mexico Grand Prix", options, 1),
        question(2, "Who'll be the fastest driver in qualifying?", options, 2),
        question(
            3, "Who qualifies highest for the Mexico City Grand Prix?", options[:2], 7
        ),
        question(
            4,
            "How far will Aston Martin get in qualifying?",
            literals("Q3", "Q2", "Q1"),
        ),
        question(5, "Who will set the fastest lap?", options, 2),
        question(6, "Which constructor will have the fastest pitstop?", options, 2),
        question(7, "Which driver finishes ahead in Grand Prix?", options),
        question(
            8,
            "How many classified finishers will there be?",
            literals("<2", "2", "3", ">3"),
            6,
        ),
        question(
            9,
            "Where will Sergio Perez finish the race?",
            literals("Podium", "4th - 10th", "11th - 22nd", "Not Classified"),
        ),
        question(
            10, "Who will leave the Grand Prix second in the championship?", options
        ),
    ]
    forecasts = model.forecast(snapshot, simulations=3000, use_telemetry=False)
    assert "unsupported" in forecasts[6]
    assert "stationary" in forecasts[6]["unsupported"].lower()
    for id_ in {2, 4, 5, 8, 9, 10}:
        assert sum(forecasts[id_]["probabilities"].values()) == pytest.approx(1)
    for p in range(3):
        assert (
            0.8
            < sum(v[p] for v in forecasts[1]["position_probabilities"].values())
            <= 1
        )
    assert sum(forecasts[3]["probabilities"].values()) <= 1
    assert not forecasts[2]["evidence"]["calibrated"]
    assert "probabilities" in forecasts[7]
    modes = {
        1: "r:podium",
        2: "q:pole",
        3: "q:quali_h2h",
        4: "q:team_qstage",
        5: "r:fastest_lap",
        7: "r:midfield",
        8: "r:classified_count:grid",
        9: "r:finish_bin",
        10: "r:champsecond",
    }
    for id_, suffix in modes.items():
        assert forecasts[id_]["model_type"].endswith(":" + suffix)
    assert len({forecasts[id_]["model_type"] for id_ in modes}) == len(modes)


def test_deterministic_and_points_and_answers_are_not_features(snapshot):
    snapshot["questions"] = [
        question(1, "Who will set the fastest lap?", snapshot["roster"], 2)
    ]
    original = model.forecast(snapshot, simulations=500, use_telemetry=False)
    changed = deepcopy(snapshot)
    changed["questions"][0]["Answer"] = [{"Id": "0"}]
    for option in changed["questions"][0]["options"]:
        option.update(points=999999, Chance="100", Position="1")
    assert model.forecast(changed, simulations=500, use_telemetry=False) == original


def test_cutoff_filters_injected_current_and_future_history(snapshot, monkeypatch):
    snapshot["questions"] = [
        question(1, "Who will set the fastest lap?", snapshot["roster"], 2)
    ]
    baseline = model.forecast(snapshot, simulations=500, use_telemetry=False)
    records = model._history(2026, None)
    for end in (snapshot["first_session_utc"], "2027-01-01T00:00:00Z"):
        leaked = deepcopy(records[-1])
        leaked.update(end=end, fastest_lap="VER", round=19)
        records.append(leaked)
    monkeypatch.setattr(model, "_history", lambda *_: records)
    assert model.forecast(snapshot, simulations=500, use_telemetry=False) == baseline
    monkeypatch.setattr(model, "_history", lambda *_: records[-2:])
    with pytest.raises(DataError, match="pre-cutoff"):
        model.forecast(snapshot, use_telemetry=False)


def test_sprint_is_a_separate_session(snapshot, monkeypatch):
    snapshot["questions"] = [
        question(
            1,
            "Where will Sergio Perez finish in the Sprint?",
            literals("Podium", "4-10", "NC"),
        )
    ]
    assert (
        "conflicts" in model.forecast(snapshot, use_telemetry=False)[1]["unsupported"]
    )
    monkeypatch.setattr(
        model, "_target", lambda s, c: Weekend(2026, 19, "Mexico", 19, c, True, False)
    )
    sprint = model.forecast(snapshot, simulations=500, use_telemetry=False)[1]
    assert sum(sprint["probabilities"].values()) == pytest.approx(1)
    assert sprint["model_type"].endswith(":s:finish_bin")


def test_unsupported_meaning_and_season_do_not_become_uniform(snapshot):
    snapshot["questions"] = [
        question(1, "Who will wear a red hat?", snapshot["roster"], 2)
    ]
    assert "unsupported" in model.forecast(snapshot, use_telemetry=False)[1]
    snapshot["questions"][0]["template"] = 5
    assert "template" in model.forecast(snapshot, use_telemetry=False)[1]["unsupported"]
    snapshot["scope"] = "season"
    assert (
        "season-horizon"
        in model.forecast(snapshot, use_telemetry=False)[1]["unsupported"]
    )


def test_both_unclassified_h2h_awards_neither(snapshot):
    question_ = question(
        1, "Who will finish ahead in the race?", snapshot["roster"][:2], 7
    )
    draws = {
        "R": {
            "ranks": np.array([[1, 2, 3, 4]]),
            "classified": np.zeros((1, 4), dtype=bool),
        }
    }
    result = model._question(question_, snapshot, snapshot["roster"], draws, [])
    assert result["probabilities"] == {"0": 0, "1": 0}
    assert result["model_type"].endswith(":r:race_h2h")


@pytest.mark.parametrize("cutoff", ["2026-10-30T00:00:00Z", "2026-12-01T00:00:00Z"])
def test_history_skips_current_and_future_before_loading(monkeypatch, cutoff):
    class Event(dict):
        def get_session_date(self, *_args, **_kwargs):
            return self["date"]

    class Schedule:
        def iterrows(self):
            return iter(
                enumerate(
                    [
                        Event(
                            RoundNumber=1,
                            EventFormat="conventional",
                            date="2026-11-01T10:00:00Z",
                        ),
                        Event(
                            RoundNumber=2,
                            EventFormat="conventional",
                            date="2027-01-01T10:00:00Z",
                        ),
                    ]
                )
            )

    monkeypatch.setattr(model, "configure_cache", lambda: None)
    monkeypatch.setattr(model.fastf1, "get_event_schedule", lambda *a, **k: Schedule())
    monkeypatch.setattr(
        model.fastf1,
        "get_session",
        lambda *a: pytest.fail("current/future session loaded"),
    )
    assert model._history(2026, model._utc(cutoff)) == []


def test_fastf1_naive_utc_is_explicitly_converted():
    assert model._fastf1_utc("2026-10-01 12:00:00").tzinfo == timezone.utc
    with pytest.raises(DataError, match="timezone"):
        model._utc("2026-10-01 12:00:00")


def test_telemetry_uses_zero_price_predict_roster_and_cutoff(snapshot, monkeypatch):
    snapshot["questions"] = [
        question(1, "Who will set the fastest lap?", snapshot["roster"], 2)
    ]

    def cached_adjustments(assets, weekends):
        assert all(a.price == 0 and a.kind == "DRIVER" for a in assets)
        assert weekends[0].first_session == model._utc(snapshot["first_session_utc"])
        return {(0, assets[0].id): (1, 0, 1)}

    monkeypatch.setattr(model, "adjustments", cached_adjustments)
    assert model.forecast(snapshot, simulations=100)[1]["evidence"][
        "telemetry_adjustments"
    ]


def test_sprint_qualifying_never_reuses_sprint_race(snapshot, monkeypatch):
    monkeypatch.setattr(
        model, "_target", lambda s, c: Weekend(2026, 19, "Mexico", 19, c, True, False)
    )
    snapshot["questions"] = [
        question(
            1, "Who qualifies highest in Sprint qualifying?", snapshot["roster"][:2], 7
        )
    ]
    assert (
        "separate session"
        in model.forecast(snapshot, use_telemetry=False)[1]["unsupported"]
    )


@pytest.fixture
def season_snapshot(snapshot, monkeypatch):
    result = deepcopy(snapshot)
    result["scope"] = "season"
    result["season_fixtures"] = []
    result["roster"] += [
        {"id": "team0", "team_id": "0", "name": "Aston Martin", "kind": 2},
        {"id": "team1", "team_id": "1", "name": "Other", "kind": 2},
    ]
    records = model._history(2026, None)

    def event(gameday, start, name, sprint):
        for kind, offset in (
            ("Sprint Qualifying" if sprint else "Qualifying", -1),
            ("Race", 0),
        ):
            time = start + timedelta(days=offset)
            result["season_fixtures"].append(
                {
                    "GamedayId": gameday,
                    "Season": "2026",
                    "IsBonusRound": 0,
                    "SessionType": kind,
                    "SessionStartDateISO8601": time.isoformat(),
                    "SessionEndDateISO8601": (time + timedelta(hours=2)).isoformat(),
                    "MeetingName": name,
                    "IsPostponed": 0,
                }
            )

    for rec in records:
        start = model._utc(rec["end"]) - timedelta(hours=6)
        rec["race_start_utc"] = start.isoformat()
        for rows in rec["sessions"].values():
            for row in rows:
                row["team_name"] = next(
                    d["team_name"] for d in snapshot["roster"] if d["tla"] == row["tla"]
                )
        # Gameday identifiers deliberately differ from FastF1 round numbers.
        event(100 + rec["round"], start, f"Earlier {rec['round']} Grand Prix", True)
    event(900, model._utc("2026-11-01T12:00:00Z"), "Future One Grand Prix", True)
    event(950, model._utc("2026-11-08T12:00:00Z"), "Future Two Grand Prix", False)
    monkeypatch.setattr(model, "_history", lambda *_: deepcopy(records))
    return result


def fixed_draw(records, drivers, simulations, rng, telemetry):
    n = len(drivers)
    return {
        **{
            kind: {
                "ranks": np.tile(np.arange(1, n + 1), (simulations, 1)),
                "classified": np.ones((simulations, n), dtype=bool),
            }
            for kind in ("Q", "R", "S")
        },
        "fastest_lap": np.zeros(simulations, dtype=int),
    }


def prior_facts(*tlas):
    return {
        "season": 2026,
        "complete": True,
        "source": "verified historical test fixture",
        "as_of_utc": "2026-01-01T00:00:00Z",
        "driver_tlas": list(tlas),
    }


def test_coherent_season_bonus_shared_world(season_snapshot, monkeypatch):
    s = season_snapshot
    drivers, teams = s["roster"][:4], s["roster"][4:]
    s["prior_grand_prix_winners"] = prior_facts("VER")
    s["prior_driver_champions"] = prior_facts("VER")
    s["questions"] = [
        question(
            99, "Predict the top 3 in the 2026 Drivers' Championship.", drivers, 1
        ),
        question(
            100,
            "Which team will take the 2026 Constructors' Championship title?",
            teams,
            2,
        ),
        question(
            101,
            "Which driver will score the most Grand Prix Pole Positions this season?",
            drivers,
            2,
        ),
        question(
            102,
            "How many first-time Grand Prix winners will we see in 2026?",
            literals("0", "1", "2", ">2"),
            6,
        ),
        question(
            103,
            "Who wins the Grand Prix qualifying head-to-head at Aston Martin this season?",
            drivers[:2],
            7,
        ),
        question(
            104, "Which team will set the fastest pitstop time of the season?", teams, 2
        ),
        question(105, "Who will win the DHL Fastest Lap Award this year?", drivers, 2),
        question(
            106, "Which team comes out on top in the Constructors’ battle?", teams, 7
        ),
        question(
            107,
            "When will the Drivers' Championship be decided?",
            literals("Future One", "Future Two", "Earlier"),
        ),
        question(
            108,
            "Will 2026 see a new driver crowned Champion?",
            literals("Yes", "No"),
            8,
        ),
        question(109, "Who will win the Drivers' Championship?", drivers, 2),
    ]
    calls = []

    def draw(*args):
        calls.append(1)
        return fixed_draw(*args)

    monkeypatch.setattr(model, "_draw", draw)
    monkeypatch.setattr(
        model, "_target", lambda *_: pytest.fail("season must use supplied fixtures")
    )
    monkeypatch.setattr(
        model,
        "adjustments",
        lambda *_: pytest.fail("future telemetry cutoff must not advance"),
    )
    output = model.forecast(s, simulations=100)
    assert len(calls) == 2  # Not one draw per fixture/session or per question.
    for id_ in set(output) - {99, 104}:
        assert sum(output[id_]["probabilities"].values()) == pytest.approx(1)
    assert output[99]["position_probabilities"]["0"] == [1, 0, 0]
    assert output[99]["position_probabilities"]["1"] == [0, 1, 0]
    assert output[109]["probabilities"]["0"] == 1
    assert output[100]["probabilities"]["team0"] == 1
    assert output[102]["probabilities"]["101"] == 1  # BEA first won this season.
    assert output[108]["probabilities"]["100"] == 1
    assert output[107]["probabilities"]["100"] == 1
    assert "Stationary" in output[104]["unsupported"]
    assert output[99]["evidence"]["simulated_gamedays"] == [900, 950]
    assert output[99]["evidence"]["sprint_gamedays"] == [900]
    assert not output[99]["evidence"]["calibrated"]


def test_season_points_constructor_attribution_and_sprint(season_snapshot, monkeypatch):
    s = season_snapshot
    records = model._history(2026, None)
    # Historical constructor points follow the actual recorded team, not today's pairing.
    for kind in ("R", "S"):
        records[0]["sessions"][kind][0]["team_name"] = "Other"
    cutoff = model._utc(s["first_session_utc"])
    monkeypatch.setattr(model, "_draw", fixed_draw)
    world = model._season_world(
        s,
        s["roster"][:4],
        records,
        model._season_events(s, cutoff),
        5,
        np.random.default_rng(1),
    )
    assert world["scores"][0].tolist() == [258, 203, 156, 109]
    assert world["team_scores"][0].tolist() == [411, 315]
    assert world["errors"] == {}


def test_season_model_deterministic_and_prior_safe(season_snapshot, monkeypatch):
    s = season_snapshot
    s["questions"] = [
        question(1, "Who will win the Drivers' Championship?", s["roster"][:4], 2)
    ]
    baseline = model.forecast(s, simulations=100, seed=42, use_telemetry=False)
    records = model._history(2026, None)
    for end in (s["first_session_utc"], "2027-01-01T00:00:00Z"):
        leaked = deepcopy(records[-1])
        leaked.update(end=end, fastest_lap="VER", round=25)
        records.append(leaked)
    calls = []

    def history(*args):
        calls.append(args)
        return records

    monkeypatch.setattr(model, "_history", history)
    changed = deepcopy(s)
    for option in changed["questions"][0]["options"]:
        option.update(points=10**9, Position="1", Chance="100")
    changed["questions"][0]["Answer"] = [{"id": "3"}]
    assert (
        model.forecast(changed, simulations=100, seed=42, use_telemetry=False)
        == baseline
    )
    assert calls == [(2026, model._utc(s["first_session_utc"]))]


def test_first_time_winners_require_career_history_and_count_unique_drivers(
    season_snapshot, monkeypatch
):
    s = season_snapshot
    s["questions"] = [
        question(
            1,
            "How many first-time Grand Prix winners will we see in 2026?",
            literals("0", "1", "2", ">2"),
            6,
        )
    ]
    missing = model.forecast(s, simulations=10, use_telemetry=False)[1]
    assert "complete sourced pre-season" in missing["unsupported"]
    s["prior_grand_prix_winners"] = prior_facts("VER")
    count = 0

    def draw(*args):
        nonlocal count
        output = fixed_draw(*args)
        # PER becomes a first-time winner; VER already had a pre-season win.
        winner = (2, 3)[count]
        output["R"]["ranks"][:, [0, winner]] = output["R"]["ranks"][:, [winner, 0]]
        count += 1
        return output

    monkeypatch.setattr(model, "_draw", draw)
    output = model.forecast(s, simulations=10, use_telemetry=False)[1]
    assert output["probabilities"]["102"] == 1  # BEA in completed history plus PER.


@pytest.mark.parametrize("change", ["missing", "incomplete", "future", "unsourced"])
def test_new_champion_needs_verified_preseason_input(
    season_snapshot, monkeypatch, change
):
    s = season_snapshot
    s["questions"] = [
        question(
            1, "Will 2026 see a new driver crowned Champion?", literals("Yes", "No"), 8
        )
    ]
    facts = prior_facts("VER")
    if change == "incomplete":
        facts["complete"] = False
    elif change == "future":
        facts["as_of_utc"] = "2027-01-01T00:00:00Z"
    elif change == "unsourced":
        facts["source"] = ""
    if change != "missing":
        s["prior_driver_champions"] = facts
    monkeypatch.setattr(model, "_draw", fixed_draw)
    assert (
        "prior_driver_champions"
        in model.forecast(s, simulations=10, use_telemetry=False)[1]["unsupported"]
    )


def test_season_rejects_partial_and_incomplete_history(season_snapshot, monkeypatch):
    monkeypatch.setattr(
        model, "_now", lambda: datetime(2026, 11, 2, tzinfo=timezone.utc)
    )
    s = season_snapshot
    s["questions"] = [
        question(1, "Who will win the Drivers' Championship?", s["roster"][:4], 2)
    ]
    s["first_session_utc"] = "2026-11-01T00:00:00Z"
    result = model.forecast(s, simulations=10, use_telemetry=False)[1]
    assert "partial session" in result["unsupported"]
    assert result["evidence"]["scope"] == "season"
    s["first_session_utc"] = "2026-10-30T12:00:00Z"
    s["season_fixtures"] = [r for r in s["season_fixtures"] if r["GamedayId"] != 101]
    assert (
        "coverage"
        in model.forecast(s, simulations=10, use_telemetry=False)[1]["unsupported"]
    )


def test_countback_and_mathematically_proven_clinch():
    scores = np.array([[100, 100], [100, 125], [150, 125]], dtype=float)
    counts = np.array([[[1, 2], [2, 0]], [[3, 0], [1, 2]], [[3, 0], [1, 2]]])
    ranks, resolved = model._rank_table(scores, counts)
    assert ranks[0].tolist() == [2, 1]  # Equal points: more wins takes the title.
    assert resolved.all()
    assert model._clinched(scores, counts, 0, 0).all()
    assert model._clinched(scores, counts, 1, 0).tolist() == [False, False, True]
    assert not model._clinched(scores[2:], counts[2:], 1, 1)[
        0
    ]  # Sprint's eight points can still matter.
    tied_ranks, valid = model._rank_table(
        np.array([[0.0, 0.0]]), np.zeros((1, 2, 2), dtype=int)
    )
    assert not valid.any()
    assert not model._clinched(
        np.array([[0.0, 0.0]]), np.zeros((1, 2, 2), dtype=int), 0, 0
    )[0]


def test_award_ties_and_unknown_predicates_remain_explicit(
    season_snapshot, monkeypatch
):
    s = season_snapshot
    cutoff = model._utc(s["first_session_utc"])
    monkeypatch.setattr(model, "_draw", fixed_draw)
    events = model._season_events(s, cutoff)
    world = model._season_world(
        s,
        s["roster"][:4],
        model._history(2026, cutoff),
        events,
        10,
        np.random.default_rng(1),
    )
    world["poles"][:, 1] = world["poles"][:, 0]
    tied = model._season_question(
        question(
            1, "Who will score the most Pole Positions this season?", s["roster"][:4], 2
        ),
        s,
        s["roster"][:4],
        events,
        world,
        cutoff,
    )
    assert "tied leaders" in tied["unsupported"]
    assert tied["evidence"]["unresolved_tie_probability"] == 1
    s["questions"] = [
        question(1, "Who will win the red hat contest?", s["roster"][:4], 2)
    ]
    assert (
        "Unrecognized"
        in model.forecast(s, simulations=10, use_telemetry=False)[1]["unsupported"]
    )
