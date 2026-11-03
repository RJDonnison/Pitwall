from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from f1fantasy import practice, racing_model, web_data, weekend_phase
from f1fantasy.data import DataError, Weekend

T0 = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # Friday FP1


def weekend(sprint=False):
    names = [
        ("Practice 1", 0, 1),
        ("Practice 2", 4, 5),
        ("Practice 3", 24, 25),
        ("Qualifying", 28, 29),
        ("Race", 48, 50),
    ]
    sessions = tuple((n, T0 + timedelta(hours=a), T0 + timedelta(hours=b)) for n, a, b in names)
    return Weekend(2026, 20, "Mexico", 20, T0, sprint, True, sessions[-1][2], sessions)


@pytest.mark.parametrize(
    "hours, state, finished",
    [
        (-10, "open", ()),
        (0.5, "practice", ()),
        (2, "practice", ("Practice 1",)),
        (26, "practice", ("Practice 1", "Practice 2", "Practice 3")),
        (28, "paused", ()),
        (40, "paused", ()),
        (49, "paused", ()),
        (60, "open", ()),
    ],
)
def test_phase_follows_the_session_clock(hours, state, finished):
    result = weekend_phase.phase([weekend()], T0 + timedelta(hours=hours))
    assert result.state == state
    if state == "practice":
        assert result.practice == finished


def test_pause_starts_with_grand_prix_qualifying_and_resumes_after_the_race():
    result = weekend_phase.phase([weekend()], T0 + timedelta(hours=30))
    assert result.pause_at == T0 + timedelta(hours=28)
    assert result.resume_after == T0 + timedelta(hours=50)
    assert result.describe()["state"] == "paused"


def test_pause_falls_back_to_second_last_session_when_qualifying_is_not_named():
    w = weekend()
    renamed = tuple(
        ("Quali", s, e) if n == "Qualifying" else (n, s, e) for n, s, e in w.sessions
    )
    w = replace(w, sessions=renamed)
    assert weekend_phase.pause_start(w) == T0 + timedelta(hours=28)


def laps(pace_by_driver, count=8):
    rows = []
    for driver, gap in pace_by_driver.items():
        for lap in range(2, 2 + count):
            rows.append(
                {
                    "Driver": driver,
                    "LapNumber": lap,
                    "Compound": "SOFT",
                    "LapTime": pd.Timedelta(seconds=float(90 * (1 + gap / 100) + (lap % 3) * 0.05)),
                    "IsAccurate": True,
                    "PitInTime": pd.NaT,
                    "PitOutTime": pd.NaT,
                    "Deleted": False,
                }
            )
    return pd.DataFrame(rows)


class Session:
    def __init__(self, pace):
        self.laps = laps(pace)


PACE = {c: g for c, g in zip("ABCDEFGH", (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7))}


def test_session_pace_orders_drivers_by_clean_fast_laps():
    pace = practice.session_pace(Session(PACE))
    ordered = sorted(pace, key=pace.get)
    assert ordered == list("ABCDEFGH")


def test_combine_is_centred_and_later_sessions_weigh_more():
    combined = practice.combine({"FP1": {"A": 1.0, "B": 0.0}, "FP3": {"A": 0.0, "B": 1.0}})
    assert abs(sum(combined.values())) < 1e-12
    assert combined["A"] < combined["B"]  # FP3 says A is faster and counts triple


def test_load_uses_only_finished_practice_and_reports_failures():
    seen = []

    def loader(season, round_number, key):
        seen.append(key)
        return Session(PACE)

    pace = practice.load(2026, 20, ("Practice 1", "Practice 2", "Qualifying"), loader=loader)
    assert seen == ["FP1", "FP2"] and set(pace) == set(PACE)
    with pytest.raises(DataError):
        practice.load(2026, 20, ("Practice 1",), loader=lambda *_: 1 / 0)


def test_practice_shrinks_pace_toward_the_practice_order_without_changing_spread():
    drivers = [{"tla": c} for c in "ABCDEFGH"]
    means = np.linspace(0, 1, 8)  # model: A fastest ... H slowest
    reversed_practice = {c: -g for c, g in zip("ABCDEFGH", np.linspace(0, 1, 8))}
    adjusted = racing_model.apply_practice(means, drivers, reversed_practice, "Q")
    assert adjusted[0] > means[0] and adjusted[-1] < means[-1]  # moved toward practice
    assert np.isclose(adjusted.mean(), means.mean())
    # No practice, too few drivers, and sprint races leave the model untouched.
    assert racing_model.apply_practice(means, drivers, None, "Q") is means
    assert racing_model.apply_practice(means, drivers, {"A": 0, "B": 1}, "Q") is means
    assert racing_model.apply_practice(means, drivers, reversed_practice, "S") is means


def test_point_estimates_move_toward_practice_order():
    scores = {c: 10 - i for i, c in enumerate("ABCDEFGH")}
    flipped = {c: -g for c, g in PACE.items()}  # practice says H is quickest
    shifted = practice.shrink_scores(scores, flipped, 0.25)
    assert shifted["H"] > scores["H"] and shifted["A"] < scores["A"]
    assert practice.shrink_scores(scores, {"A": 0.0}, 0.25) == scores


GOOD = {
    "schema_version": 1,
    "status": "ready",
    "generated_at": "2026-10-29T08:00:00+00:00",
    "rounds": [{"round": 20}],
}


def test_load_previous_requires_a_ready_forecast(tmp_path):
    path = tmp_path / "previous.json"
    assert web_data.load_previous(path) is None
    path.write_text("not json")
    assert web_data.load_previous(path) is None
    path.write_text(json.dumps({"status": "unavailable", "message": "x"}))
    assert web_data.load_previous(path) is None
    path.write_text(json.dumps(GOOD))
    assert web_data.load_previous(path) == GOOD


def test_paused_weekend_publishes_the_previous_forecast_with_its_true_age(monkeypatch, tmp_path):
    monkeypatch.setattr(web_data.data, "season_weekends", lambda season: [weekend()])
    monkeypatch.setattr(
        web_data, "build", lambda *a, **k: pytest.fail("must not rebuild while paused")
    )
    out = web_data.produce(
        2026, now=T0 + timedelta(hours=30), previous=GOOD, history=None, archive_path=tmp_path / "a.json"
    )
    assert out["status"] == "ready" and out["generated_at"] == GOOD["generated_at"]
    state = out["publication_state"]
    assert state["mode"] == "carried_forward" and state["state"] == "paused"
    assert state["last_updated"] == GOOD["generated_at"]


def test_failed_refresh_keeps_the_last_forecast_and_only_unavailable_without_one(monkeypatch, tmp_path):
    monkeypatch.setattr(web_data.data, "season_weekends", lambda season: [weekend()])
    monkeypatch.setattr(web_data.public_history, "repository", lambda *_: _Null())
    monkeypatch.setattr(web_data.forecast_archive, "load", lambda *_: {})

    def broken(*a, **k):
        raise DataError("roster not published")

    monkeypatch.setattr(web_data, "build", broken)
    now = T0 + timedelta(hours=60)  # after the race: normal refresh path
    kept = web_data.produce(2026, now=now, previous=GOOD, history=None, archive_path=tmp_path / "a")
    assert kept["status"] == "ready"
    assert "roster not published" in kept["publication_state"]["reason"]
    empty = web_data.produce(2026, now=now, previous=None, history=None, archive_path=tmp_path / "a")
    assert empty["status"] == "unavailable"


class _Null:
    def __enter__(self):
        return {}

    def __exit__(self, *exc):
        return False


class DataNotLoadedError(Exception):
    """Same name as fastf1.exceptions.DataNotLoadedError (not an AttributeError)."""


class NoLapTiming:
    results = pd.DataFrame()

    @property
    def laps(self):
        raise DataNotLoadedError("The data you are trying to access has not been loaded yet")


def test_session_without_lap_timing_is_treated_as_no_laps_not_a_crash():
    from f1fantasy import session_laps

    assert session_laps.loaded_laps(NoLapTiming()) is None
    assert practice.session_pace(NoLapTiming()) == {}
    with pytest.raises(ZeroDivisionError):  # other errors are not swallowed

        class Broken:
            @property
            def laps(self):
                return 1 / 0

        session_laps.loaded_laps(Broken())


def test_estimate_assets_passes_practice_through_the_joint_model_wrapper(monkeypatch):
    """Regression: the wrapper once rejected ``practice`` with a TypeError."""
    from f1fantasy import projections
    from f1fantasy.data import Asset
    from f1fantasy.projections import Estimate

    assets = tuple(
        Asset(str(i), f"D{i}", "DRIVER", str(i // 2), 50, "ABCDEFGH"[i]) for i in range(8)
    ) + tuple(Asset(f"c{i}", f"T{i}", "CONSTRUCTOR", str(i), 50) for i in range(4))
    base = {(0, a.id): Estimate(10 - int(a.id) if a.kind == "DRIVER" else 5, 0, 20) for a in assets}
    monkeypatch.setattr(projections, "_estimate_legacy", lambda *a, **k: dict(base))
    flipped = {c: -g for c, g in PACE.items()}
    for joint in (False, True):
        if joint:
            import f1fantasy.fantasy_model as fm

            monkeypatch.setattr(fm, "forecast", lambda assets, weekends, baseline, **k: dict(baseline))
        out = projections.estimate_assets(
            assets, [None], use_joint_model=joint, practice=flipped
        )
        assert out[0, "7"].qualifying > base[0, "7"].qualifying  # slowest-by-model now helped
        assert out[0, "0"].qualifying < base[0, "0"].qualifying
        # constructor shifts by its drivers' combined change
        shift = sum(out[0, str(i)].qualifying - base[0, str(i)].qualifying for i in (0, 1))
        assert out[0, "c0"].qualifying == pytest.approx(base[0, "c0"].qualifying + shift)
        assert out[0, "0"].sprint == base[0, "0"].sprint
    untouched = projections.estimate_assets(assets, [None], use_joint_model=False)
    assert untouched == base
