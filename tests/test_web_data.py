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
        lambda *a: ChipValues(nn, ap, {0: (18,), 1: (18,)}, (13,)),
    )
    return assets


def test_publication_includes_all_remaining_inputs_and_no_account_data(public):
    result = web_data.build(2026)
    assert result["preview_only"] and result["status"] == "ready"
    assert len(result["rounds"]) == 2 and len(result["assets"]) == 9
    assert result["rounds"][0]["forecasts"]["0"] == (2, 0, 10)
    assert result["rounds"][0]["no_negative"]["0"] == (1, 0, 2)
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
    assert not result["chip_support"]["no_negative"]["available"]
    assert result["chip_support"]["x3"]["available"]
    assert "autopilot" not in result["rounds"][0]


def test_failed_refresh_publishes_unavailable_not_old_forecasts(tmp_path, monkeypatch):
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
