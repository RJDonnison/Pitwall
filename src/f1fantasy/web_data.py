"""Publish only public, pre-weekend inputs for the static browser optimizer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import data, output
from .chips import CHIPS, components, load_chip_values, valid_estimate
from .projections import estimate_assets


def build(season: int, *, telemetry: bool = True) -> dict:
    live, weekends = data.snapshot(season)
    forecasts = estimate_assets(live.assets, weekends, use_telemetry=telemetry)
    for t, weekend in enumerate(weekends):
        for asset in live.assets:
            if not valid_estimate(forecasts[t, asset.id]):
                raise data.DataError(f"Missing finite forecast for {asset.name}")
    support = {name: {"available": True} for name in CHIPS}
    try:
        values = load_chip_values(live.assets, weekends, forecasts)
    except data.DataError as exc:
        values = None
        for name in ("autopilot", "no_negative"):
            support[name] = {"available": False, "reason": str(exc)}
    rounds = []
    for t, weekend in enumerate(weekends):
        row = output.event(weekend)
        row["forecasts"] = {a.id: components(forecasts[t, a.id]) for a in live.assets}
        if values is not None:
            row["no_negative"] = {
                a.id: components(values.no_negative[t, a.id]) for a in live.assets
            }
            row["autopilot"] = [
                {key: components(score) for key, score in scenario.items()}
                for scenario in values.autopilot[t]
            ]
            row["history_gamedays"] = values.history_gamedays[t]
        rounds.append(row)
    generated = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "status": "ready",
        "season": season,
        "generated_at": generated.isoformat(),
        "price_checked_at": live.fetched_at.isoformat(),
        "price_published_at": live.published_at.isoformat(),
        "forecast_cutoff": min(weekends[0].first_session, generated).isoformat(),
        "price_gameday_id": live.weekend.gameday_id,
        "assets": [{**output.asset(a), "tla": a.tla} for a in live.assets],
        "rounds": rounds,
        "chip_support": support,
        "skipped_history_gamedays": values.skipped_history_gamedays if values else [],
        "model": {
            "telemetry": telemetry,
            "risk": True,
            "future_prices_assumed_constant": True,
        },
        "preview_only": True,
        "notice": "Published forecasts are a planning preview. Verify current prices, roster, budget, transfers and chip eligibility on the official game before changing your team.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--output", type=Path, default=Path("web/public/forecast.json"))
    parser.add_argument("--no-telemetry", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = build(args.season, telemetry=not args.no_telemetry)
    except (data.DataError, OSError, ValueError) as exc:
        # A failed publication replaces prior data with an explicit unavailable
        # state; Pages must never keep serving old forecasts as current data.
        payload = {
            "schema_version": 1,
            "status": "unavailable",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "message": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n"
    )
    print(f"Published {payload['status']} forecast data to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
