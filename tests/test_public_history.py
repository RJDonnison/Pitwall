from datetime import datetime, timezone
import json

import pytest

from f1fantasy import data, predict_model, projections, public_history as archive


def document():
    return {
        "schema": 1,
        "events": {
            "2026/1": {
                "RoundNumber": 1,
                "EventName": "Example Grand Prix",
                "Location": "Example",
                "EventFormat": "conventional",
                "race_start": "2026-03-01T12:00:00+00:00",
            }
        },
        "scores": {
            "2026/1/R": {
                "completed_at": "2026-03-01T18:00:00+00:00",
                "values": {"AAA": 25.0},
            }
        },
        "fantasy_events": {"1": "2026-03-01T18:00:00+00:00"},
        "fantasy": {"1": []},
        "racing": [
            {
                "season": 2026,
                "round": 1,
                "end": "2026-03-01T18:00:00+00:00",
                "sessions": {},
            }
        ],
        "features": [],
    }


def write(tmp_path, content=None):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(document() if content is None else content))
    return path


def test_repository_reads_without_any_fastf1_requests(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Pages must not download raw FastF1 history")

    for name in ("get_event", "get_event_schedule", "get_session"):
        monkeypatch.setattr(archive.fastf1, name, fail)
    with archive.repository(write(tmp_path)):
        assert archive.event(2026, 1)["Location"] == "Example"
        assert archive.event(2026, "Example Grand Prix")["RoundNumber"] == 1
        assert projections._session_scores(2026, 1, "R") == {"AAA": 25}
        assert len(archive.schedule(2026)) == 1
        assert (
            len(predict_model._history(2026, datetime(2026, 4, 1, tzinfo=timezone.utc)))
            == 1
        )


def test_missing_history_fails_without_fallback(tmp_path):
    with archive.repository(write(tmp_path)):
        with pytest.raises(data.DataError, match="no session"):
            archive.scores(2026, 1, "Q", lambda: pytest.fail("network fallback"))
        with pytest.raises(data.DataError, match="no event"):
            archive.event(2026, 2)
    assert archive.current() is None


def test_failed_update_keeps_previous_data_and_restores_context(tmp_path):
    path = write(tmp_path)
    original = path.read_bytes()
    with pytest.raises(RuntimeError):
        with archive.repository(path, update=True) as stored:
            stored["racing"] = []
            raise RuntimeError("interrupted updater")
    assert archive.current() is None
    assert path.read_bytes() == original


def test_historical_source_cannot_supply_live_prices(tmp_path, monkeypatch):
    calls = []

    def live(path):
        calls.append(path)
        raise data.DataError("fresh server unavailable")

    monkeypatch.setattr(data, "_get_json", live)
    with archive.repository(write(tmp_path)):
        with pytest.raises(data.DataError, match="fresh server"):
            data.load_assets(1)
    assert calls == ["drivers/1_en.json"]


def test_future_records_cannot_enter_earlier_prediction(tmp_path):
    with archive.repository(write(tmp_path)):
        assert (
            archive.racing_record(2026, 1, datetime(2026, 2, 1, tzinfo=timezone.utc))
            is None
        )
        with pytest.raises(data.DataError, match="unfinished"):
            archive.fantasy_feed(
                "drivers/999_en.json", lambda _: pytest.fail("network")
            )


def test_bundled_archive_has_public_inputs_and_no_credentials():
    with archive.repository() as stored:
        assert stored["coverage"]["race_records"] >= 1
        text = json.dumps(stored).lower()
        for secret in ('"cookie"', '"password"', '"guid"', '"binding"', '"token"'):
            assert secret not in text


@pytest.mark.parametrize("cached", [False, True])
def test_updater_preserves_bundled_features_without_a_runner_cache(
    tmp_path, monkeypatch, cached
):
    from f1fantasy import refresh_history as updater

    now = datetime.now(timezone.utc)
    original = {
        "year": now.year,
        "round": 1,
        "session_number": 5,
        "completed_at": f"{now.year}-01-01T00:00:00+00:00",
        "drivers": {},
        "track": {"speed_kmh": 200},
    }
    content = document()
    content["features"] = [original]
    path = write(tmp_path, content)
    replacement = dict(original, track={"speed_kmh": 210})
    monkeypatch.setattr(updater.history, "configure_cache", lambda: None)
    monkeypatch.setattr(
        updater.history,
        "historical_features",
        lambda _: [replacement] if cached else [],
    )
    monkeypatch.setattr(archive, "schedule", lambda _: None)
    monkeypatch.setattr(updater.data, "season_weekends", lambda _: [])
    monkeypatch.setattr(updater.predict_model, "_history", lambda *a: [])
    monkeypatch.setattr(updater.web_data, "build", lambda _: {"price_gameday_id": 19})

    assert updater.main(["--season", str(now.year), "--output", str(path)]) == 0
    updated = json.loads(path.read_text())
    assert updated["features"] == [replacement if cached else original]
    assert updated["coverage"]["telemetry_summaries"] == 1
