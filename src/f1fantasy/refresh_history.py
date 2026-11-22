"""Refresh compact public model inputs; the Pages build never downloads sessions."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import (
    data,
    history,
    predict_model,
    public_history,
    web_data,
    insights,
    racing_data,
    practice_archive,
    predict_evidence,
    circuit_info,
)


def check_live_inputs(season, weekends, now):
    """Exercise the live forecast inputs without making history depend on the game.

    This is a check on the upcoming-venue, session and chip inputs, not a data
    source, so the Fantasy game being closed must not discard a refresh whose
    historical work is already done. From qualifying until the race finishes, and
    again until the game publishes the next round's roster, ``data.snapshot``
    rightly refuses to build a forecast and the Pages workflow keeps the last
    published one. That is the normal state of every race weekend. With no upcoming
    weekend left in the season there is nothing to exercise. Any other
    ``DataError`` is a real fault and still fails the refresh.
    """
    upcoming = [w for w in weekends if w.first_session > now]
    if not upcoming:
        return {"next_gameday": None, "live_inputs": "season_complete"}
    try:
        result = web_data.build(season)
    except data.RosterNotPublished:
        return {
            "next_gameday": upcoming[0].gameday_id,
            "live_inputs": "roster_not_published",
        }
    return {"next_gameday": result["price_gameday_id"], "live_inputs": "verified"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--output", type=Path, default=public_history.DEFAULT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    history.configure_cache()
    features = history.historical_features(now)
    with public_history.repository(args.output, update=True) as document:
        # Prune before enrichment so discarded seasons cannot trigger downloads.
        public_history.prune(document, args.season)
        # A fresh runner may have no local telemetry cache. Preserve the compact
        # observations already committed, replacing them only with newer extracts.
        summaries = {
            (row["year"], row["round"], row["session_number"]): row
            for row in document["features"] + features
            if args.season - 2 <= row["year"] <= args.season
            and public_history.date(row["completed_at"]) < now
        }
        features = [summaries[key] for key in sorted(summaries)]
        for year in range(args.season - 2, args.season + 1):
            public_history.schedule(year)
        circuit_info.refresh(document, args.season, now)
        weekends = data.season_weekends(args.season)
        document["fantasy_events"] = {
            str(w.gameday_id): w.last_session.isoformat()
            for w in weekends
            if w.last_session is not None and w.last_session < now
        }
        document["fantasy"] = {
            day: rows
            for day, rows in document["fantasy"].items()
            if day in document["fantasy_events"]
        }
        document["features"] = features
        # Keep official round prices for Garage trends. These are historical
        # snapshots only; live roster/prices still come from data.snapshot.
        for day in document["fantasy_events"]:
            public_history.fantasy_feed(f"drivers/{day}_en.json", data._get_json)
        predict_model._history(args.season, now)
        racing_data.refresh(document, args.season - 2, args.season, now)
        practice_archive.backfill(document, now)
        racing_data.refresh_stops(document, now)
        insights.refresh_pitstops(document, args.season, now)
        predict_evidence.refresh_observations(document, now)
        predict_evidence.refresh_facts(document, args.season, now)
        # This exercises the actual upcoming-venue/session/chip inputs, not an
        # unrelated bulk download. Existing completed racing rows are reused.
        live = check_live_inputs(args.season, weekends, now)
        document["coverage"] = {
            "season": args.season,
            "next_gameday": live["next_gameday"],
            "live_inputs": live["live_inputs"],
            "race_records": len(document["racing"]),
            "session_scores": len(document["scores"]),
            "telemetry_summaries": len(features),
        }
    print(f"Updated public history: {document['coverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
