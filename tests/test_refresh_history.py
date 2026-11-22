"""The history refresh must not depend on the Fantasy game being open."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from f1fantasy import data, public_history
from f1fantasy import refresh_history as updater
import test_public_history as fixtures

NOW = datetime.now(timezone.utc)


def weekend(round_, first, last):
    return data.Weekend(
        2026, round_, f"Round {round_}", round_, first, False, False, last_session=last
    )


def race_weekend_schedule():
    """Round 21 is under way, so round 22 is the next one and has no roster yet."""
    return [
        weekend(20, NOW - timedelta(days=10), NOW - timedelta(days=8)),
        weekend(21, NOW - timedelta(days=1), NOW + timedelta(hours=3)),
        weekend(22, NOW + timedelta(days=6), NOW + timedelta(days=8)),
    ]


def refresh(tmp_path, monkeypatch, weekends, build):
    """Run the real updater with every download replaced; return the history path."""
    path = fixtures.write(tmp_path)
    monkeypatch.setattr(updater.history, "configure_cache", lambda: None)
    monkeypatch.setattr(updater.history, "historical_features", lambda _: [])
    monkeypatch.setattr(public_history, "schedule", lambda _: None)
    monkeypatch.setattr(public_history, "fantasy_feed", lambda *a, **k: None)
    monkeypatch.setattr(updater.circuit_info, "refresh", lambda *a: None)
    monkeypatch.setattr(updater.data, "season_weekends", lambda _: weekends)
    monkeypatch.setattr(updater.predict_model, "_history", lambda *a: [])
    monkeypatch.setattr(updater.racing_data, "refresh", lambda *a: None)
    monkeypatch.setattr(updater.racing_data, "refresh_stops", lambda *a: None)
    monkeypatch.setattr(updater.practice_archive, "backfill", lambda *a: None)
    monkeypatch.setattr(updater.insights, "refresh_pitstops", lambda *a: None)
    monkeypatch.setattr(updater.predict_evidence, "refresh_observations", lambda *a: None)
    monkeypatch.setattr(updater.predict_evidence, "refresh_facts", lambda *a: None)
    monkeypatch.setattr(updater.web_data, "build", build)
    return path


def coverage(path):
    return json.loads(path.read_text())["coverage"]


def unpublished(season):
    raise data.RosterNotPublished(
        "Fantasy roster for race week 22 has not been published yet"
    )


def test_unpublished_next_roster_during_a_race_weekend_does_not_discard_the_refresh(
    tmp_path, monkeypatch
):
    path = refresh(tmp_path, monkeypatch, race_weekend_schedule(), unpublished)
    assert updater.main(["--season", "2026", "--output", str(path)]) == 0
    stored = json.loads(path.read_text())
    # The atomic write happened: the finished round was recorded.
    assert list(stored["fantasy_events"]) == ["20"]
    assert stored["coverage"]["next_gameday"] == 22
    assert stored["coverage"]["live_inputs"] == "roster_not_published"


def test_other_live_data_faults_still_fail_and_keep_the_committed_history(
    tmp_path, monkeypatch
):
    def stale(season):
        raise data.DataError("Fantasy price feed is stale or dated in the future")

    path = refresh(tmp_path, monkeypatch, race_weekend_schedule(), stale)
    before = path.read_bytes()
    with pytest.raises(data.DataError, match="stale"):
        updater.main(["--season", "2026", "--output", str(path)])
    assert path.read_bytes() == before


def test_a_published_roster_is_still_exercised_and_reported(tmp_path, monkeypatch):
    seen = []

    def build(season):
        seen.append(season)
        return {"price_gameday_id": 22}

    schedule = [
        weekend(20, NOW - timedelta(days=10), NOW - timedelta(days=8)),
        weekend(22, NOW + timedelta(days=2), NOW + timedelta(days=4)),
    ]
    path = refresh(tmp_path, monkeypatch, schedule, build)
    assert updater.main(["--season", "2026", "--output", str(path)]) == 0
    assert seen == [2026]
    assert coverage(path)["next_gameday"] == 22
    assert coverage(path)["live_inputs"] == "verified"


def test_a_finished_season_has_nothing_to_exercise(tmp_path, monkeypatch):
    def build(season):
        pytest.fail("No upcoming weekend, so there are no live inputs to check")

    schedule = [weekend(20, NOW - timedelta(days=10), NOW - timedelta(days=8))]
    path = refresh(tmp_path, monkeypatch, schedule, build)
    assert updater.main(["--season", "2026", "--output", str(path)]) == 0
    assert coverage(path)["next_gameday"] is None
    assert coverage(path)["live_inputs"] == "season_complete"
