from datetime import datetime, timezone

import pandas as pd

from f1fantasy import projections
from f1fantasy.data import Asset, Weekend


def test_sprint_uses_prior_results_only(monkeypatch):
    assets = (
        Asset("a", "A", "DRIVER", "team", 50, "AAA"),
        Asset("b", "B", "DRIVER", "team", 50, "BBB"),
        Asset("c", "Team", "CONSTRUCTOR", "team", 50),
    )
    first = Weekend(
        2026, 3, "Sprint", 3, datetime(2026, 3, 10, tzinfo=timezone.utc), True, False
    )
    second = Weekend(
        2026, 4, "Regular", 4, datetime(2026, 3, 20, tzinfo=timezone.utc), False, False
    )

    class Event(dict):
        def get_session_date(self, *_args, **_kwargs):
            import pandas as pd

            return pd.Timestamp("2026-03-05")

    monkeypatch.setattr(projections, "fastf1_weekend", lambda _: None)
    monkeypatch.setattr(projections, "season_weekends", lambda _: [])
    monkeypatch.setattr(
        projections.fastf1, "get_event", lambda *_: Event(EventFormat="sprint")
    )
    monkeypatch.setattr(
        projections.fastf1,
        "get_event_schedule",
        lambda *_: {"RoundNumber": [0, 1, 2, 3]},
    )
    calls = []

    def scores(_year, round_number, kind):
        calls.append((round_number, kind))
        return {"AAA": 8.0, "BBB": 5.0}

    monkeypatch.setattr(projections, "_session_scores", scores)
    result = projections.estimate_assets(assets, [first, second])
    assert {(1, "Q"), (1, "R"), (1, "S"), (2, "Q"), (2, "R"), (2, "S")} <= set(calls)
    assert result[0, "a"].sprint == 8.0
    assert result[1, "a"].sprint == 0
    assert result[0, "c"].sprint == 13.0


def test_unclassified_sprint_and_race_are_penalized(monkeypatch):
    class Session:
        results = pd.DataFrame(
            [
                {
                    "Abbreviation": "AAA",
                    "Position": 20,
                    "ClassifiedPosition": "R",
                    "GridPosition": 4,
                }
            ]
        )

        def load(self, **_kwargs):
            pass

    monkeypatch.setattr(projections.fastf1, "get_session", lambda *_: Session())
    assert projections._session_scores(2026, 1, "S")["AAA"] == -10
    assert projections._session_scores(2026, 1, "R")["AAA"] == -20


def test_official_bonuses_use_only_earlier_completed_races(monkeypatch):
    assets = (
        Asset("a", "A", "DRIVER", "team", 50, "AAA"),
        Asset("b", "B", "DRIVER", "team", 50, "BBB"),
        Asset("c", "Team", "CONSTRUCTOR", "team", 50),
    )
    target = Weekend(
        2026, 3, "Target", 3, datetime(2026, 3, 10, tzinfo=timezone.utc), True, False
    )
    previous = Weekend(
        2026,
        2,
        "Prior",
        2,
        datetime(2026, 3, 3, tzinfo=timezone.utc),
        True,
        True,
        datetime(2026, 3, 4, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(projections, "fastf1_weekend", lambda _: None)
    monkeypatch.setattr(projections, "season_weekends", lambda _: [previous, target])
    monkeypatch.setattr(
        projections.fastf1, "get_event_schedule", lambda *_: {"RoundNumber": [0, 1]}
    )

    class Event(dict):
        def get_session_date(self, *_args, **_kwargs):
            return pd.Timestamp("2026-03-03")

    monkeypatch.setattr(
        projections.fastf1, "get_event", lambda *_: Event(EventFormat="sprint")
    )
    monkeypatch.setattr(projections, "_session_scores", lambda *_: {"AAA": 2, "BBB": 2})
    fetched = []

    def official(id_, _sprint):
        fetched.append(id_)
        return {"a": (10, 20, 30), "b": (5, 5, 10), "c": (25, 30, 55)}

    monkeypatch.setattr(projections, "completed_scores", official)
    result = projections.estimate_assets(assets, [target])
    assert fetched == [2]
    assert result[0, "a"].sprint > 10
    assert result[0, "c"].race > 40
