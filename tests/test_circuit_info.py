"""Official metadata is season-bound display context, never a racing model input."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from f1fantasy import circuit_info as module, public_history
from f1fantasy.data import DataError, Weekend
from f1fantasy.race_context import race_context
import test_public_history as fixtures

NOW = datetime(2027, 3, 1, tzinfo=timezone.utc)
SOURCE = f"{module.BASE}/en/racing/2027/new-venue"
EVENT = {
    "EventName": "New Venue Grand Prix",
    "Location": "New City",
    "race_start": "2027-03-14T15:00:00+00:00",
}
CALENDAR = '<a href="/en/racing/2027/testing">Testing</a><a href="/en/racing/2027/new-venue"><span>ROUND</span> 1 New Venue</a>'


def html():
    sport = {
        "@type": "SportsEvent",
        "@id": SOURCE,
        "startDate": "2027-03-12T00:00:00Z",
        "endDate": "2027-03-14T23:59:59Z",
        "location": {"name": "New City"},
    }
    fields = {
        "Circuit Length": "5.123km",
        "Number of Laps": "60",
        "Race Distance": "307.380km",
        "First Grand Prix": "2027",
        "Fastest lap time": "1:20.123",
    }
    return (
        f'<script type="application/ld+json">{json.dumps(sport)}</script><dl>'
        + "".join(
            f"<div><dt>{key}</dt><dd>{value}</dd><span>{'Record Driver (2026)' if key == 'Fastest lap time' else ''}</span></div>"
            for key, value in fields.items()
        )
        + '</dl><img src="https://media.formula1.com/image/upload/v1/common/f1/2027/track/newdetailed.webp"><img src="https://media.formula1.com/image/upload/v1/Racehub%20header/new.webp"><details><summary>What’s the circuit like?</summary><p>A new layout with &amp; a long straight.</p></details><p>Race winner: not a circuit feature</p>'
    )


def parsed(text=None):
    return module.parse(
        text or html(),
        season=2027,
        number=1,
        event=EVENT,
        source=SOURCE,
        checked_at=NOW,
    )


def test_new_season_calendar_discovers_rounds_without_fixed_slugs():
    assert module.calendar(CALENDAR, 2027) == {1: SOURCE}
    reordered = CALENDAR.replace("ROUND</span> 1", "ROUND</span> 9")
    assert module.calendar(reordered, 2027) == {9: SOURCE}
    with pytest.raises(DataError, match="ambiguous"):
        module.calendar(
            CALENDAR + CALENDAR.replace("new-venue", "different-venue"), 2027
        )
    with pytest.raises(DataError, match="no round"):
        module.calendar(CALENDAR, 2028)


def test_specs_description_and_remote_maps_come_from_current_official_page():
    result = parsed()
    assert result["spec"] == {
        "length_km": 5.123,
        "race_laps": 60,
        "race_distance_km": 307.38,
    }
    assert result["description"] == "A new layout with & a long straight."
    assert result["first_gp"] == 2027
    assert result["lap_record"] == "1:20.123"
    assert result["record_driver"] == "Record Driver (2026)"
    assert result["map_asset"].endswith("newdetailed.webp")
    assert result["photo_asset"].startswith("https://media.formula1.com/")
    assert "Race winner" not in json.dumps(result)


@pytest.mark.parametrize(
    "old,new",
    [
        ("2027/new-venue", "2026/new-venue"),
        ("2027-03-12", "2027-04-12"),
        ("New City", "Different Venue"),
        ("5.123km", "0km"),
        ("media.formula1.com", "untrusted.example"),
        ("60</dd>", "unknown</dd>"),
    ],
)
def test_wrong_season_dates_specifications_or_image_sources_are_rejected(old, new):
    with pytest.raises((DataError, ValueError)):
        parsed(html().replace(old, new))


def test_refresh_is_metadata_only_daily_and_replaces_changed_layouts(monkeypatch):
    document = {"events": {"2027/1": EVENT}}
    calls = []
    page = html()

    def fetch(url):
        calls.append(url)
        assert url.startswith(module.BASE)
        return CALENDAR if url.endswith("/2027") else page

    monkeypatch.setattr(module, "_html", fetch)
    module.refresh(document, 2027, NOW)
    assert calls == [f"{module.BASE}/en/racing/2027", SOURCE]
    module.refresh(document, 2027, NOW + timedelta(hours=1))
    assert calls.count(SOURCE) == 1
    page = page.replace("5.123km", "5.456km").replace(
        "newdetailed.webp", "changed-detailed.webp"
    )
    module.refresh(document, 2027, NOW + timedelta(days=1))
    assert document["circuits"]["2027/1"]["spec"]["length_km"] == 5.456
    assert "changed-detailed" in document["circuits"]["2027/1"]["map_asset"]


def test_outage_preserves_original_provenance_and_cancels_removed_rounds(monkeypatch):
    old = parsed()
    document = {
        "events": {"2027/1": EVENT},
        "circuits": {"2027/1": deepcopy(old), "2027/2": deepcopy(old)},
    }

    def fail(url):
        if url.endswith("/2027"):
            return CALENDAR
        raise requests.Timeout("offline")

    monkeypatch.setattr(module, "_html", fail)
    module.refresh(document, 2027, NOW + timedelta(days=2))
    assert document["circuits"] == {"2027/1": old}


def test_unknown_venue_publishes_specs_and_map_without_guessing_coordinates(
    tmp_path, monkeypatch
):
    stored = fixtures.document()
    stored["events"] = {"2027/1": EVENT}
    stored["circuits"] = {"2027/1": parsed()}
    path = fixtures.write(tmp_path, stored)
    weekend = Weekend(
        2027,
        1,
        EVENT["EventName"],
        1,
        NOW + timedelta(days=11),
        False,
        False,
        NOW + timedelta(days=13),
    )
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: pytest.fail(
            "Publication must not fetch circuit metadata or guess weather"
        ),
    )
    with public_history.repository(path):
        result = race_context(weekend, now=NOW)
        assert result["track_spec"]["season"] == 2027
        assert result["track_spec"]["length_km"] == 5.123
        assert result["circuit"]["source"] == SOURCE
        assert result["weather"] == {"status": "unavailable"}
    stored["events"]["2027/1"] = dict(EVENT, EventName="Replaced Venue Grand Prix")
    path = fixtures.write(tmp_path, stored)
    with public_history.repository(path):
        assert module.lookup(weekend) is None
