"""Stable, versioned structures shared by CLI text and JSON output."""

from __future__ import annotations

from datetime import datetime, timezone

from .backtest import BacktestRow
from .data import Asset, Weekend
from .projections import Estimate

SCHEMA_VERSION = 1


def envelope(
    command: str, data: dict, warnings: list[str] | None = None, status: str = "ok"
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "warnings": warnings or [],
    }


def event(weekend: Weekend) -> dict:
    return {
        "season": weekend.season,
        "round": weekend.round,
        "name": weekend.name,
        "gameday_id": weekend.gameday_id,
        "sprint": weekend.sprint,
        "first_session_utc": weekend.first_session.isoformat(),
        "locked": weekend.locked,
    }


def asset(item: Asset) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "team_id": item.team_id,
        "price_tenths_m": item.price,
        "season_points": item.season_points,
    }


def estimate(points: Estimate) -> dict:
    return {
        "qualifying": points.qualifying,
        "sprint": points.sprint,
        "race": points.race,
        "total": points.total,
    }


def backtest_row(row: BacktestRow) -> dict:
    return {
        "event": event(row.weekend),
        "sample_size": {"drivers": row.drivers, "constructors": row.constructors},
        "mae_points": {
            "drivers": row.driver_error,
            "constructors": row.constructor_error,
            "qualifying_all_assets": row.qualifying_error,
            "sprint_all_assets": row.sprint_error,
            "race_all_assets": row.race_error,
            "race_drivers": row.driver_race_error,
            "race_constructors": row.constructor_race_error,
        },
        "signed_bias_points": {
            "qualifying_all_assets": row.qualifying_bias,
            "sprint_all_assets": row.sprint_bias,
            "race_all_assets": row.race_bias,
        },
        "naive_last_3_races": {
            "driver_samples": row.baseline_driver_count,
            "driver_race_mae": row.baseline_driver_race_error,
            "model_driver_race_mae_same_samples": row.model_driver_race_error_on_baseline,
        },
        "selection_diagnostics": row.selection,
        "assets": [
            {
                "id": entry.id,
                "name": entry.name,
                "kind": entry.kind,
                "predicted_points": estimate(entry.predicted),
                "actual_points": estimate(entry.actual),
                "naive_last_3_race_points": entry.baseline_race_points,
                "signed_error_points": entry.error,
            }
            for entry in row.assets
        ],
    }
