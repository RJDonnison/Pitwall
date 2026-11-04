"""Retention removes old model inputs without refetching or erasing useful facts."""

from copy import deepcopy
import json
import pytest

from f1fantasy import forecast_archive, public_history, prune_history, refresh_history
import test_public_history as fixtures


def history():
    document = fixtures.document()
    for year in (2024, 2025):
        document["events"][f"{year}/1"] = deepcopy(document["events"]["2026/1"])
        document["scores"][f"{year}/1/R"] = {"values": {"AAA": 10}}
        document["racing"].append({"season": year, "round": 1})
        document["fantasy_events"][str(year)] = f"{year}-03-01T18:00:00+00:00"
        document["fantasy"][str(year)] = [{"PlayerId": year}]
    document["fantasy"]["unused"] = []
    document["circuits"] = {
        f"{year}/1": {"season": year} for year in (2024, 2025, 2026)
    }
    for name in ("stationary_stops", "predict_races", "pitstop_winners"):
        document[name] = [{"season": year} for year in (2024, 2025, 2026)]
    document["features"] = [
        {
            "year": year,
            "round": 1,
            "session_number": 5,
            "completed_at": f"{year}-01-01T00:00:00+00:00",
        }
        for year in (2024, 2025, 2026)
    ]
    document["predict_facts"] = {
        "winner_history_complete": True,
        "winners": [
            {"end": "1950-05-13T18:00:00+00:00", "driver_name": "Historic winner"}
        ],
    }
    document["coverage"] = {"race_records": 3}
    return document


def test_2027_prunes_2024_everywhere_but_preserves_needed_historic_winners():
    document = history()
    facts = deepcopy(document["predict_facts"])
    removed = public_history.prune(document, 2027)
    assert removed["events"] == removed["scores"] == removed["racing"] == 1
    assert removed["fantasy"] == 2
    assert set(document["events"]) == {"2025/1", "2026/1"}
    assert set(document["circuits"]) == {"2025/1", "2026/1"}
    assert [row["year"] for row in document["features"]] == [2025, 2026]
    for name in ("racing", "stationary_stops", "predict_races", "pitstop_winners"):
        assert {row["season"] for row in document[name]} == {2025, 2026}
    assert document["predict_facts"] == facts
    assert document["coverage"]["race_records"] == 2
    assert all(value == 0 for value in public_history.prune(document, 2027).values())


def test_pruning_command_is_offline_and_first_forecasts_within_window_are_unchanged(
    tmp_path, monkeypatch
):
    path = fixtures.write(tmp_path, history())
    archive_path = tmp_path / "forecasts.json"
    rows = [
        {"season": year, "round": 1, "forecasts": {"original": [year]}}
        for year in (2024, 2025, 2026)
    ]
    forecast_archive.save({"schema": 1, "forecasts": rows}, archive_path)

    def fail(*args, **kwargs):
        raise AssertionError("Pruning must not download inputs")

    for name in ("get_event", "get_event_schedule", "get_session"):
        monkeypatch.setattr(public_history.fastf1, name, fail)
    assert (
        prune_history.main(
            [
                "--season",
                "2027",
                "--history",
                str(path),
                "--forecasts",
                str(archive_path),
            ]
        )
        == 0
    )
    assert forecast_archive.load(archive_path)["forecasts"] == rows[1:]
    assert "2024/1" not in json.loads(path.read_text())["events"]


def test_refresh_discards_old_years_before_any_enricher_can_request_them(
    tmp_path, monkeypatch
):
    # The refresh fails later deliberately; its atomic writer must keep the original.
    path = fixtures.write(tmp_path, history())
    before = path.read_bytes()
    monkeypatch.setattr(refresh_history.history, "configure_cache", lambda: None)
    monkeypatch.setattr(refresh_history.history, "historical_features", lambda _: [])

    def check(year):
        assert year >= 2025
        document = public_history.current()["document"]
        assert all(row["season"] >= 2025 for row in document["racing"])
        assert "2024/1" not in document["events"]
        raise RuntimeError("Verified pruning before enrichment")

    monkeypatch.setattr(public_history, "schedule", check)
    with pytest.raises(RuntimeError, match="before enrichment"):
        refresh_history.main(["--season", "2027", "--output", str(path)])
    assert path.read_bytes() == before
