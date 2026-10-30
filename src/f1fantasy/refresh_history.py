"""Refresh compact public model inputs; the Pages build never downloads sessions."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import data, history, predict_model, public_history, web_data, insights


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--output", type=Path, default=public_history.DEFAULT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    history.configure_cache()
    features = history.historical_features(now)
    with public_history.repository(args.output, update=True) as document:
        # A fresh runner may have no local telemetry cache. Preserve the compact
        # observations already committed, replacing them only with newer extracts.
        summaries = {
            (row["year"], row["round"], row["session_number"]): row
            for row in document["features"] + features
            if now.year - 2 <= row["year"] <= now.year
            and public_history.date(row["completed_at"]) < now
        }
        features = [summaries[key] for key in sorted(summaries)]
        for year in range(args.season - 2, args.season + 1):
            public_history.schedule(year)
        document["fantasy_events"] = {
            str(w.gameday_id): w.last_session.isoformat()
            for w in data.season_weekends(args.season)
            if w.last_session is not None and w.last_session < now
        }
        document["features"] = features
        # Keep official round prices for Garage trends. These are historical
        # snapshots only; live roster/prices still come from data.snapshot.
        for day in document["fantasy_events"]:
            public_history.fantasy_feed(f"drivers/{day}_en.json", data._get_json)
        predict_model._history(args.season, now)
        insights.refresh_pitstops(document, args.season, now)
        # This exercises the actual upcoming-venue/session/chip inputs, not an
        # unrelated bulk download. Existing completed racing rows are reused.
        result = web_data.build(args.season)
        document["coverage"] = {
            "season": args.season,
            "next_gameday": result["price_gameday_id"],
            "race_records": len(document["racing"]),
            "session_scores": len(document["scores"]),
            "telemetry_summaries": len(features),
        }
    print(f"Updated public history: {document['coverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
