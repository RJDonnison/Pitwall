"""Only public pre-weekend inputs enter the static publication."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from f1fantasy import web_data
from f1fantasy.chips import ChipValues
from f1fantasy.data import Asset, DataError, Snapshot, Weekend
from f1fantasy.projections import Estimate


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(web_data, "race_context", lambda weekend: {})
    now = datetime.now(timezone.utc)
    w = Weekend(
        2026,
        19,
        "Mexico",
        19,
        now + timedelta(days=2),
        False,
        False,
        last_session=now + timedelta(days=4),
    )
    assets = tuple(
        Asset(
            str(i), f"Asset {i}", "DRIVER" if i < 6 else "CONSTRUCTOR", str(i // 2), 50
        )
        for i in range(9)
    )
    live = Snapshot(w, assets, now, now)
    monkeypatch.setattr(
        web_data.data,
        "snapshot",
        lambda season: (
            live,
            [
                w,
                replace(
                    w,
                    round=20,
                    gameday_id=20,
                    first_session=w.first_session + timedelta(days=7),
                    last_session=w.last_session + timedelta(days=7),
                ),
            ],
        ),
    )

    def estimates(roster, weekends, **kwargs):
        return {
            (t, a.id): Estimate(2, 0, 10)
            for t, _ in enumerate(weekends)
            for a in roster
        }

    monkeypatch.setattr(web_data, "estimate_assets", estimates)
    nn = {(t, a.id): Estimate(1, 0, 2) for t in range(2) for a in assets}
    ap = {
        t: ({a.id: Estimate(2, 0, 10) for a in assets if a.kind == "DRIVER"},)
        for t in range(2)
    }
    monkeypatch.setattr(
        web_data,
        "load_chip_values",
        lambda *a: ChipValues(
            nn,
            ap,
            {0: (18,), 1: (18,)},
            (13,),
            joint={
                t: (
                    {
                        "scores": {a.id: Estimate(2, 0, 10) for a in assets},
                        "no_negative": {a.id: Estimate(3, 0, 12) for a in assets},
                    },
                )
                for t in range(2)
            },
        ),
    )
    return assets


def test_publication_includes_all_remaining_inputs_and_no_account_data(public):
    result = web_data.build(2026)
    assert result["preview_only"] and result["status"] == "ready"
    assert len(result["rounds"]) == 2 and len(result["assets"]) == 9
    assert result["rounds"][0]["forecasts"]["0"] == (2, 0, 10)
    assert result["rounds"][0]["no_negative"]["0"] == (0, 0, 0)
    assert result["rounds"][0]["joint_scenarios"][0]["scores"]["6"] == (2, 0, 10)
    assert result["rounds"][0]["joint_scenarios"][0]["no_negative"]["0"] == (3, 0, 12)
    assert result["skipped_history_gamedays"] == (13,)
    assert result["forecast_cutoff"] < result["rounds"][0]["first_session_utc"]
    assert all(
        row["first_session_utc"] < row["last_session_utc"] for row in result["rounds"]
    )
    assert not {"guid", "binding", "answers", "team", "cookie"} & result.keys()
    json.dumps(result, allow_nan=False)


def test_missing_empirical_history_disables_chips_instead_of_zero_imputation(
    public, monkeypatch
):
    def missing(*a):
        raise DataError("No same-format history")

    monkeypatch.setattr(web_data, "load_chip_values", missing)
    result = web_data.build(2026)
    assert not result["chip_support"]["autopilot"]["available"]
    assert result["chip_support"]["no_negative"]["available"]
    assert result["rounds"][0]["no_negative"]["0"] == (0, 0, 0)
    assert result["chip_support"]["x3"]["available"]
    assert "autopilot" not in result["rounds"][0]


def test_failed_refresh_without_any_previous_forecast_is_unavailable(
    tmp_path, monkeypatch
):
    path = tmp_path / "forecast.json"
    path.write_text('{"status":"ready"}')

    def failed(*a, **k):
        raise DataError("Live roster not verified")

    monkeypatch.setattr(web_data, "build", failed)
    assert web_data.main(["--output", str(path)]) == 0
    assert json.loads(path.read_text())["status"] == "unavailable"


def test_price_history_uses_recorded_values_and_fresh_current_price(
    public, monkeypatch
):
    source = {
        "fantasy_events": {"17": "2026-09-01T12:00:00Z", "18": "2026-10-01T12:00:00Z"},
        "fantasy": {
            "17": [{"PlayerId": "0", "Value": "4.8"}],
            "18": [
                {"PlayerId": "0", "Value": "4.9"},
                {"PlayerId": "1", "Value": None},
            ],
        },
    }
    monkeypatch.setattr(
        web_data.public_history, "current", lambda: {"document": source}
    )
    result = web_data.build(2026)
    assert result["price_history"]["0"] == [
        {"gameday_id": 17, "price_tenths_m": 48},
        {"gameday_id": 18, "price_tenths_m": 49},
        {"gameday_id": 19, "price_tenths_m": 50},
    ]
    assert result["price_history"]["1"] == [{"gameday_id": 19, "price_tenths_m": 50}]


def test_selected_weather_forecasts_feed_chip_planning_and_publication(
    public, monkeypatch
):
    def candidate(assets, weekend, forecasts, weather, document, cutoff):
        return dict(
            status="candidate",
            samples={"0/Q": 3},
            applied=False,
            baseline_forecasts=forecasts,
            forecasts={key: [q + 3, s, r + 7] for key, (q, s, r) in forecasts.items()},
        )

    seen = {}

    monkeypatch.setattr(web_data.weather_model, "candidate", candidate)

    # No empirical chip samples, so only inspect the forecasts supplied to chips.
    def unavailable_chips(assets, weekends, forecasts):
        seen.update(forecasts)
        raise DataError("No same-format chip history")

    monkeypatch.setattr(web_data, "load_chip_values", unavailable_chips)
    result = web_data.build(2026)
    assert result["rounds"][0]["forecasts"]["0"] == (5, 0, 17)
    assert seen[0, "0"] == Estimate(5, 0, 17)
    weather = result["rounds"][0]["weather_model"]
    assert weather["applied"] and weather["status"] == "selected"
    assert weather["baseline_forecasts"]["0"] == (2, 0, 10)
    assert result["model"]["weather"] == web_data.weather_model.VERSION


def test_practice_phase_targets_the_weekend_in_progress_with_practice_pace(
    public, monkeypatch
):
    from f1fantasy import weekend_phase

    now = datetime.now(timezone.utc)
    current = Weekend(
        2026,
        19,
        "Mexico",
        19,
        now - timedelta(hours=3),
        False,
        True,
        now + timedelta(days=2),
        (
            ("Practice 1", now - timedelta(hours=3), now - timedelta(hours=2)),
            ("Qualifying", now + timedelta(hours=20), now + timedelta(hours=21)),
            ("Race", now + timedelta(days=1), now + timedelta(days=2)),
        ),
    )
    seen, practice_seen = {}, {}
    live_assets = web_data.data.snapshot(2026)[0].assets
    base_live = Snapshot(current, live_assets, now, now)

    def snapshot(season, at=None, **kwargs):
        seen.update(at=at, **kwargs)
        return base_live, [
            current,
            replace(
                current,
                round=20,
                gameday_id=20,
                first_session=now + timedelta(days=6),
                last_session=now + timedelta(days=8),
            ),
        ]

    monkeypatch.setattr(web_data.data, "snapshot", snapshot)
    original = web_data.estimate_assets

    def estimates(roster, weekends, **kwargs):
        practice_seen.update(kwargs)
        return original(roster, weekends, **kwargs)

    monkeypatch.setattr(web_data, "estimate_assets", estimates)
    pace = {"A": -0.2, "B": 0.1}
    monkeypatch.setattr(web_data.practice_model, "load", lambda *a, **k: pace)
    phase = weekend_phase.Phase(
        weekend_phase.PRACTICE,
        current,
        now + timedelta(hours=20),
        current.last_session,
        ("Practice 1",),
    )
    result = web_data.build(2026, phase=phase)
    assert seen["at"] == current.first_session - timedelta(seconds=1)
    assert seen["allow_old_prices"] is True
    assert practice_seen["practice"] == pace
    assert result["model"]["practice"]["used"] is True
    assert result["model"]["practice"]["sessions"] == ["Practice 1"]
    assert result["publication_state"]["state"] == "practice"
    assert result["publication_state"]["mode"] == "live"


def test_practice_that_cannot_load_degrades_to_the_plain_forecast(public, monkeypatch):
    from f1fantasy import weekend_phase

    live, weekends = web_data.data.snapshot(2026)
    monkeypatch.setattr(web_data.data, "snapshot", lambda *a, **k: (live, weekends))

    def broken(*a, **k):
        raise DataError("FP1 laps unavailable")

    monkeypatch.setattr(web_data.practice_model, "load", broken)
    phase = weekend_phase.Phase(
        weekend_phase.PRACTICE,
        weekends[0],
        weekends[0].last_session,
        weekends[0].last_session,
        ("Practice 1",),
    )
    result = web_data.build(2026, phase=phase)
    assert result["status"] == "ready"
    assert result["model"]["practice"]["used"] is False
    assert "FP1 laps unavailable" in result["model"]["practice"]["error"]


def test_publication_reports_the_committed_model_fit(public):
    result = web_data.build(2026)
    fit = result["model"]["fit"]
    assert fit["evaluated_races"] >= 24
    assert fit["pre_weekend"]["params"]["half_life"] > 0
    assert fit["gate"]["min_gain"] > 0
    assert set(fit["practice"]) >= {"status", "weights"}
    assert 50 < fit["pre_weekend"]["accuracy"] < 100
    assert "previous_accuracy" in fit["pre_weekend"]
    assert result["model"]["practice"]["validated"] is (
        fit["practice"]["status"] == "fitted"
    )
    json.dumps(result, allow_nan=False)
