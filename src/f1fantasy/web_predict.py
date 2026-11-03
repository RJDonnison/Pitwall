"""Publish fresh, public-only F1 Predict recommendations for the website."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from . import predict, predict_data, public_history
from .data import DataError


def build(season, *, telemetry=True):
    """Keep Predict availability independent from Fantasy's market/publication."""
    checked = datetime.now(timezone.utc)
    try:
        snapshot = predict_data.fetch(season)
        publication = {
            "schema_version": 1,
            "status": "ready",
            "source": predict_data.BASE,
            "season": season,
            "gameday_id": snapshot["gameday_id"],
            "race_id": snapshot["race_id"],
            "fetched_at": snapshot["fetched_at"],
            "first_session_utc": snapshot["first_session_utc"],
            "deadline_utc": snapshot["deadline_utc"],
            "deadline_authority": snapshot["deadline_authority"],
            "locked": snapshot["locked"],
            "question_fingerprint": predict_data.fingerprint(snapshot),
            "questions": snapshot["questions"],
            "simulations": 4000,
            "seed": 2026,
            "telemetry": telemetry,
            "recommendation": None,
        }
        if snapshot["locked"] or checked >= predict_data.utc(
            snapshot["first_session_utc"]
        ):
            publication.update(
                status="locked",
                message="Recommendations are pre-weekend only. This official round is locked or has already started.",
            )
        else:
            publication["recommendation"] = predict.recommend(
                snapshot, use_telemetry=telemetry, risk_profiles=True
            )
        return publication
    except (DataError, OSError, ValueError) as exc:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "fetched_at": checked.isoformat(),
            "message": str(exc),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--output", type=Path, default=Path("web/public/predict.json"))
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument("--no-telemetry", action="store_true")
    args = parser.parse_args(argv)
    with public_history.repository(args.history):
        payload = build(args.season, telemetry=not args.no_telemetry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n"
    )
    print(f"Published {payload['status']} Predict data to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
