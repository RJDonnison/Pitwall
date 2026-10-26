import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from f1fantasy import prior_history
from f1fantasy.data import DataError, Weekend


def fixture(monkeypatch):
    weekends = [
        Weekend(
            2025,
            i,
            f"Race {i}",
            i,
            datetime(2025, 3, i, tzinfo=timezone.utc),
            False,
            True,
        )
        for i in range(1, 9)
    ]
    monkeypatch.setattr(prior_history, "configure_cache", lambda *_: None)
    monkeypatch.setattr(prior_history, "_calendar", lambda _: weekends)
    calls = []

    def scores(year, round_number, kind):
        calls.append((round_number, kind))
        return {f"D{i}": float(round_number + i) for i in range(20)}

    monkeypatch.setattr(prior_history, "_session_scores", scores)

    class Session:
        results = pd.DataFrame(
            [
                {
                    "Abbreviation": f"D{i}",
                    "TeamId": f"team{i // 2}",
                    "TeamName": f"Team {i // 2}",
                    "FullName": f"Driver {i}",
                }
                for i in range(20)
            ]
        )

        def load(self, **_kwargs):
            pass

    monkeypatch.setattr(prior_history.fastf1, "get_session", lambda *_: Session())
    return calls


def test_reconstruct_prior_proxy_and_resume(tmp_path, monkeypatch):
    calls = fixture(monkeypatch)
    weeks, source = prior_history.load_previous_season(2026, root=tmp_path)
    assert source == "fastf1_proxy" and len(weeks) == 8
    assert len(weeks[0].assets) == 30
    assert weeks[0].scores["D0"].race == 1
    calls.clear()
    again, _ = prior_history.load_previous_season(2026, root=tmp_path)
    assert again == weeks and not calls


def test_official_import_overrides_proxy_and_validates(tmp_path, monkeypatch):
    fixture(monkeypatch)
    prior_history.load_previous_season(2026, root=tmp_path)
    proxy = json.loads((tmp_path / "prior-proxy/v1-2025.json").read_text())
    proxy["weeks"][0]["assets"][0]["race"] = 42.0
    imported = tmp_path / "official.json"
    imported.write_text(json.dumps(proxy))
    weeks, source = prior_history.load_previous_season(
        2026, root=tmp_path, official_file=imported
    )
    assert source == "imported_official" and weeks[0].scores["D0"].race == 42
    proxy["weeks"][0]["assets"][0]["race"] = float("nan")
    imported.write_text(json.dumps(proxy))
    with pytest.raises(DataError, match="Invalid prior-season points"):
        prior_history.load_previous_season(2026, root=tmp_path, official_file=imported)
