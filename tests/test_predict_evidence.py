"""Evidence collection boundaries: source completeness, chronology and missing timing."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from f1fantasy import predict_evidence as evidence
from f1fantasy.data import DataError


def test_winner_pagination_counts_shared_winners_and_excludes_future_results(
    monkeypatch,
):
    calls = []

    def driver(name):
        return {
            "driverId": name,
            "givenName": name,
            "familyName": "Driver",
            "code": name.upper(),
            "nationality": "Thai",
        }

    def get(url, params, timeout):
        calls.append((url, params["offset"]))
        if url.endswith("results/1.json"):
            offset = params["offset"]
            rows = [driver("one"), driver("two")] if offset == 0 else [driver("future")]
            body = {
                "offset": str(offset),
                "total": "3",
                "RaceTable": {
                    "Races": [
                        {
                            "raceName": "British Grand Prix",
                            "date": "1950-05-13" if offset == 0 else "2027-05-13",
                            "Results": [{"position": "1", "Driver": d} for d in rows],
                        }
                    ]
                },
            }
        else:
            body = {
                "offset": "0",
                "total": "1",
                "DriverTable": {"Drivers": [driver("one")]},
            }
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"MRData": body}
        )

    monkeypatch.setattr(evidence.requests, "get", get)
    monkeypatch.setattr(evidence.time, "sleep", lambda _: None)
    document = {}
    evidence.refresh_facts(document, 2026, datetime(2026, 10, 1, tzinfo=timezone.utc))
    facts = document["predict_facts"]
    assert facts["winner_history_complete"] is True
    assert [w["tla"] for w in facts["winners"]] == ["ONE", "TWO"]
    assert facts["winners"][0]["end"] == "1950-05-14T00:00:00+00:00"
    assert facts["drivers"][0]["nationality"] == "Thai"
    assert [offset for url, offset in calls if url.endswith("results/1.json")] == [0, 2]


@pytest.mark.parametrize(
    "bad", ["offset", "total", "empty", "nonwinner", "nationality"]
)
def test_incomplete_sources_do_not_replace_verified_facts(monkeypatch, bad):
    def get(url, params, timeout):
        if not url.endswith("results/1.json"):
            body = {"offset": "0", "total": "1", "DriverTable": {"Drivers": []}}
        elif params["offset"] == 0:
            body = {
                "offset": "1" if bad == "offset" else "0",
                "total": "1" if bad == "nationality" else "2",
                "RaceTable": {
                    "Races": [
                        {
                            "raceName": "British Grand Prix",
                            "date": "1950-05-13",
                            "Results": [
                                {
                                    "position": "2" if bad == "nonwinner" else "1",
                                    "Driver": {
                                        "givenName": "One",
                                        "familyName": "Driver",
                                    },
                                }
                            ],
                        }
                    ]
                },
            }
        else:
            body = {
                "offset": "1",
                "total": "3" if bad == "total" else "2",
                "RaceTable": {"Races": []},
            }
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"MRData": body}
        )

    monkeypatch.setattr(evidence.requests, "get", get)
    monkeypatch.setattr(evidence.time, "sleep", lambda _: None)
    document = {"predict_facts": {"source": "previous verified facts"}}
    with pytest.raises(DataError):
        evidence.refresh_facts(
            document, 2026, datetime(2026, 10, 1, tzinfo=timezone.utc)
        )
    assert document == {"predict_facts": {"source": "previous verified facts"}}


def test_race_control_missing_messages_are_not_a_zero_event_race():
    session = SimpleNamespace(
        race_control_messages=pd.DataFrame(),
        results=pd.DataFrame({"Laps": [pd.NA, 20]}),
    )
    assert evidence.race_observation(session) == {}


def test_deployments_with_unknown_laps_keep_unknown_windows_and_vsc_can_recur():
    messages = pd.DataFrame(
        [
            {"Message": "VIRTUAL SAFETY CAR DEPLOYED", "Lap": None},
            {"Message": "VIRTUAL SAFETY CAR ENDING", "Lap": 3},
            {"Message": "VIRTUAL SAFETY CAR DEPLOYED", "Lap": 6},
        ]
    )
    result = evidence.race_observation(
        SimpleNamespace(race_control_messages=messages, results=None)
    )
    assert result["safety_laps"] == [None, 6]


def test_observation_refresh_respects_cutoff_version_and_unavailable_messages(
    monkeypatch,
):
    import fastf1
    from f1fantasy import history

    calls = []
    monkeypatch.setattr(history, "configure_cache", lambda: None)

    def get_session(season, number, kind):
        calls.append(number)
        messages = (
            pd.DataFrame([{"Message": "TRACK CLEAR", "Lap": 3}])
            if number == 1
            else pd.DataFrame()
        )
        return SimpleNamespace(
            load=lambda **kwargs: None,
            race_control_messages=messages,
            results=pd.DataFrame({"Laps": [20, 20]}),
        )

    monkeypatch.setattr(fastf1, "get_session", get_session)
    document = {
        "racing": [
            {
                "season": 2026,
                "round": i,
                "end": "2026-09-01T12:00:00Z" if i < 3 else "2026-11-01T12:00:00Z",
            }
            for i in (1, 2, 3)
        ]
    }
    cutoff = datetime(2026, 10, 1, tzinfo=timezone.utc)
    evidence.refresh_observations(document, cutoff)
    assert calls == [1, 2]
    assert len(document["predict_races"]) == 1
    assert document["predict_races"][0]["safety_laps"] == []
    evidence.refresh_observations(document, cutoff)
    assert calls == [1, 2, 2]
