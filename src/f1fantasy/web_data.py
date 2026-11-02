"""Publish only public, pre-weekend inputs for the static browser optimizer."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (
    data,
    output,
    public_history,
    insights,
    fantasy_model,
    forecast_archive,
    weather_model,
    accuracy,
    practice as practice_model,
    weekend_phase,
)
from .chips import CHIPS, components, load_chip_values, valid_estimate
from .projections import Estimate, estimate_assets
from .race_context import race_context


def model_fit_summary():
    """What the scheduled fit last did, for the site (None when never fitted)."""
    from . import racing_model

    fit = racing_model.FIT
    if not fit:
        return None
    document = fit["document"]

    def family(key):
        part = document[key]
        decision = part.get("decision", {})
        return {
            "params": part["params"],
            "objective": part.get("objective"),
            "defaults_objective": part.get("defaults_objective"),
            "gain_vs_defaults": part.get("gain_vs_defaults"),
            "gain_vs_defaults_interval90": part.get("gain_vs_defaults_interval90"),
            "latest_decision": {
                "adopted": decision.get("adopted"),
                "reason": decision.get("reason"),
                "holdout_gain": decision.get("gain_holdout"),
            },
            "metrics": part.get("metrics"),
            "default_metrics": part.get("default_metrics"),
        }

    return {
        "fitted_at": document.get("fitted_at"),
        "evaluated_races": document.get("evaluated_races"),
        "last_race": document.get("last_race"),
        "pre_weekend": family("pre"),
        "post_qualifying": family("post_qualifying"),
        "practice": {
            k: document.get("practice", {}).get(k)
            for k in ("status", "weights", "races_with_practice", "needed")
        },
        "recent": [
            {
                "at": e.get("at"),
                "races": e.get("races"),
                "pre_adopted": e.get("pre", {}).get("adopted"),
                "post_adopted": e.get("post_qualifying", {}).get("adopted"),
            }
            for e in document.get("log", [])[-5:]
        ],
        "gate": document.get("gate"),
    }


def racing_model_weights():
    from .racing_model import PRACTICE_WEIGHT

    return dict(PRACTICE_WEIGHT)


def price_history(live):
    """Optional recorded round prices, never predictive or a live-price fallback."""
    source = public_history.current()
    document = source["document"] if source else {}
    result = {a.id: [] for a in live.assets}
    events = document.get("fantasy_events", {})
    for day in sorted(events, key=lambda d: public_history.date(events[d])):
        for row in document.get("fantasy", {}).get(day, []):
            key = str(row.get("PlayerId"))
            if key not in result or row.get("Value") is None:
                continue
            try:
                value = Decimal(str(row["Value"])) * 10
                if (
                    not value.is_finite()
                    or value <= 0
                    or value != value.to_integral_value()
                ):
                    continue
                result[key].append(
                    {"gameday_id": int(day), "price_tenths_m": int(value)}
                )
            except (InvalidOperation, ValueError):
                continue
    for a in live.assets:
        result[a.id] = [
            p for p in result[a.id] if p["gameday_id"] != live.weekend.gameday_id
        ]
        result[a.id].append(
            {"gameday_id": live.weekend.gameday_id, "price_tenths_m": a.price}
        )
    return result


def build(
    season: int, *, telemetry: bool = True, archive=None, phase=None, practice_loader=None
) -> dict:
    phase = phase or weekend_phase.Phase(weekend_phase.OPEN, None)
    pace, practice_error = {}, None
    if phase.state == weekend_phase.PRACTICE:
        # The weekend in progress is the forecast target until qualifying; its
        # Fantasy roster is already published even though the game is locked.
        live, weekends = data.snapshot(
            season,
            phase.weekend.first_session - timedelta(seconds=1),
            allow_old_prices=True,
        )
        try:
            pace = practice_model.load(
                season, phase.weekend.round, phase.practice, loader=practice_loader
            )
        except data.DataError as exc:
            practice_error = str(exc)
    else:
        live, weekends = data.snapshot(season)
    contexts = [race_context(weekend) for weekend in weekends]
    generated = datetime.now(timezone.utc)
    cutoff = min(weekends[0].first_session, generated)
    document = (public_history.current() or {}).get("document", {})
    archive = archive if archive is not None else {"schema": 1, "forecasts": []}
    forecasts = estimate_assets(
        live.assets, weekends, use_telemetry=telemetry, practice=pace or None
    )
    weather_models = []
    for t, weekend in enumerate(weekends):
        weather = weather_model.candidate(
            live.assets,
            weekend,
            {a.id: components(forecasts[t, a.id]) for a in live.assets},
            contexts[t].get("weather", {}),
            document,
            cutoff,
        )
        if weather["status"] == "candidate":
            weather["applied"] = any(n >= 3 for n in weather["samples"].values())
            weather["status"] = (
                "selected" if weather["applied"] else "insufficient_history"
            )
            weather["reason"] = (
                "Pre-weekend weather adjustment selected"
                if weather["applied"]
                else "Fewer than three matching same-format weather observations; base estimates retained"
            )
            for a in live.assets:
                forecasts[t, a.id] = Estimate(*weather["forecasts"][a.id])
        weather_models.append(weather)
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
        row["last_session_utc"] = (
            weekend.last_session.isoformat() if weekend.last_session else None
        )
        row.update(contexts[t])
        row["forecasts"] = {a.id: components(forecasts[t, a.id]) for a in live.assets}
        row["weather_model"] = weather_models[t]
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
    publication = {
        "schema_version": 1,
        "status": "ready",
        "season": season,
        "historical_data": public_history.current()["document"].get("coverage")
        if public_history.current()
        else None,
        "generated_at": generated.isoformat(),
        "price_checked_at": live.fetched_at.isoformat(),
        "price_published_at": live.published_at.isoformat(),
        "forecast_cutoff": cutoff.isoformat(),
        "insights": insights.build(
            live.assets,
            weekends,
            cutoff,
            telemetry=telemetry,
            practice=pace or None,
        ),
        "price_gameday_id": live.weekend.gameday_id,
        "price_history": price_history(live),
        "assets": [{**output.asset(a), "tla": a.tla} for a in live.assets],
        "rounds": rounds,
        "chip_support": support,
        "skipped_history_gamedays": values.skipped_history_gamedays if values else [],
        "publication_state": {
            **phase.describe(),
            "mode": "live",
            "last_updated": generated.isoformat(),
        },
        "model": {
            "telemetry": telemetry,
            "practice": {
                "used": bool(pace),
                "sessions": list(phase.practice) if pace else [],
                "drivers": len(pace),
                "error": practice_error,
                "weights": {
                    "racing_model": racing_model_weights(),
                    "fantasy_points": practice_model.POINTS_WEIGHT,
                },
                "validated": (model_fit_summary() or {})
                .get("practice", {})
                .get("status")
                == "fitted",
            },
            "fit": model_fit_summary(),
            "risk": True,
            "weather": weather_model.VERSION,
            "historical_mae_scope": "Base Fantasy model replay excludes weather; weather_evaluation and accuracy use archived forward forecasts",
            "future_prices_assumed_constant": True,
            "fantasy": {
                k: v
                for k, v in fantasy_model.report(
                    live.assets,
                    cutoff,
                    telemetry=telemetry,
                ).items()
                if k != "folds"
            },
        },
        "preview_only": True,
        "notice": "Published forecasts are a planning preview. Verify current prices, roster, budget, transfers and chip eligibility on the official game before changing your team.",
    }
    settlements = forecast_archive.settled(archive, document, cutoff)
    publication["weather_evaluation"] = weather_model.evaluation(
        settlements, publication["model"]
    )
    publication["accuracy"] = accuracy.report(
        settlements,
        publication["model"],
        generated,
    )
    for row, weekend in zip(rounds, weekends):
        row["baseline"] = accuracy.baseline(
            live.assets, document, cutoff, weekend.sprint
        )
        row["intervals"] = accuracy.intervals(
            live.assets, row["forecasts"], weekend.sprint, publication["accuracy"]
        )
    publication["generated_at"] = datetime.now(timezone.utc).isoformat()
    return publication


def load_previous(path):
    """The last good published forecast, or None when there is not one."""
    try:
        previous = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    ok = (
        isinstance(previous, dict)
        and previous.get("status") == "ready"
        and isinstance(previous.get("rounds"), list)
        and previous["rounds"]
    )
    return previous if ok else None


def carry_forward(previous, phase, reason):
    """Re-publish the last good forecast, truthfully labelled.

    ``generated_at`` is left alone so every page shows when the numbers were
    really produced; only ``publication_state`` says why they were not refreshed.
    """
    carried = dict(previous)
    carried["publication_state"] = {
        **phase.describe(),
        "mode": "carried_forward",
        "reason": reason,
        "last_updated": previous.get("generated_at"),
    }
    return carried


def produce(season, *, now, previous, history, archive_path, telemetry=True):
    """Fresh forecast when the weekend phase allows it, otherwise the last good one.

    The site must never go blank: a paused weekend, an unpublished roster or a
    failed refresh all keep the previous forecast, and ``unavailable`` is only
    published when there has never been a good forecast to show.
    """
    phase = weekend_phase.Phase(weekend_phase.OPEN, None)
    try:
        phase = weekend_phase.phase(data.season_weekends(season), now)
    except (data.DataError, OSError, ValueError):
        pass  # schedule unavailable: try a normal refresh, fall back below
    if phase.state == weekend_phase.PAUSED and previous:
        return carry_forward(
            previous, phase, "Predictions are paused from qualifying until the race finishes."
        )
    try:
        with public_history.repository(history):
            archive = forecast_archive.load(archive_path)
            payload = build(season, telemetry=telemetry, archive=archive, phase=phase)
            forecast_archive.capture(archive, payload)
            forecast_archive.save(archive, archive_path)
        return payload
    except (data.DataError, OSError, ValueError) as exc:
        if previous:
            return carry_forward(previous, phase, f"Latest refresh unavailable: {exc}")
        return {
            "schema_version": 1,
            "status": "unavailable",
            "generated_at": now.isoformat(),
            "message": str(exc),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--output", type=Path, default=Path("web/public/forecast.json"))
    parser.add_argument("--no-telemetry", action="store_true")
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    parser.add_argument("--archive", type=Path, default=forecast_archive.DEFAULT)
    parser.add_argument(
        "--previous",
        type=Path,
        default=Path(".f1fantasy/previous-forecast.json"),
        help="last published forecast.json, kept on the site when no new one can be made",
    )
    args = parser.parse_args(argv)
    payload = produce(
        args.season,
        now=datetime.now(timezone.utc),
        previous=load_previous(args.previous),
        history=args.history,
        archive_path=args.archive,
        telemetry=not args.no_telemetry,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n"
    )
    mode = payload.get("publication_state", {}).get("mode", payload["status"])
    print(f"Published {payload['status']} ({mode}) forecast data to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
