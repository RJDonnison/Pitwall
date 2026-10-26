from datetime import datetime, timezone

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
    monkeypatch.setattr(
        projections.fastf1, "get_event", lambda *_: Event(EventFormat="sprint")
    )
    calls = []

    def scores(_year, round_number, kind):
        calls.append((round_number, kind))
        return {"AAA": 8.0, "BBB": 5.0}

    monkeypatch.setattr(projections, "_session_scores", scores)
    result = projections.estimate_assets(assets, [first, second])
    assert set(calls) == {(1, "Q"), (1, "R"), (1, "S"), (2, "Q"), (2, "R"), (2, "S")}
    assert result[0, "a"].sprint == 8.0
    assert result[1, "a"].sprint == 0
    assert result[0, "c"].sprint == 13.0
