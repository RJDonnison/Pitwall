"""Read-only F1 Fantasy command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .backtest import run_backtest
from .data import DataError, load_statistics, snapshot
from .history import cache_status, preload
from .optimizer import optimize
from .output import asset as asset_output
from .output import backtest_row, envelope, event as event_output
from .projections import estimate_assets

DEFAULT_STATE = Path(".f1fantasy/team.json")


def _money(value: object) -> int:
    try:
        amount = Decimal(str(value)) * 10
        if amount <= 0 or amount != amount.to_integral_value():
            raise ValueError("Budget must be positive and in $0.1m increments")
        return int(amount)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Budget must be a positive dollar amount in millions") from exc


def _read_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
        if not isinstance(state, dict):
            raise ValueError("Team state must be a JSON object")
        return state
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise DataError(f"Cannot read team state {path}: {exc}") from exc


def _validate_state(
    state: dict, assets: tuple, season: int
) -> tuple[frozenset[str], int, int]:
    try:
        if int(state["season"]) != season:
            raise DataError("Team season differs from live Fantasy season")
        if not isinstance(state["drivers"], list) or not isinstance(
            state["constructors"], list
        ):
            raise DataError("Team driver and constructor IDs must be JSON lists")
        drivers = [str(id_) for id_ in state["drivers"]]
        constructors = [str(id_) for id_ in state["constructors"]]
        if len(drivers) != 5 or len(constructors) != 2:
            raise DataError("Team must have exactly five drivers and two constructors")
        chosen = drivers + constructors
        if len(set(chosen)) != 7:
            raise DataError("Team has duplicate Fantasy IDs")
        catalog = {a.id: a for a in assets}
        if any(id_ not in catalog or catalog[id_].kind != "DRIVER" for id_ in drivers):
            raise DataError("Imported driver is missing or inactive in the live roster")
        if any(
            id_ not in catalog or catalog[id_].kind != "CONSTRUCTOR"
            for id_ in constructors
        ):
            raise DataError(
                "Imported constructor is missing or inactive in the live roster"
            )
        budget = _money(state["budget"])
        if sum(catalog[id_].price for id_ in chosen) > budget:
            raise DataError(
                "Imported team exceeds the provided budget at fetched prices"
            )
        carry = int(state.get("carry", 0))
        if carry not in (0, 1):
            raise DataError("Carry must be zero or one")
        return frozenset(chosen), budget, carry
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(f"Invalid team import: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only F1 Fantasy team recommendations"
    )
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Import your existing Fantasy team")
    source = init.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--import-file",
        type=Path,
        help="JSON with season, budget, drivers, constructors and carry",
    )
    source.add_argument(
        "--drivers", nargs=5, metavar="ID", help="Five driver Fantasy IDs"
    )
    init.add_argument("--constructors", nargs=2, metavar="ID")
    init.add_argument("--budget", help="Current team budget in $m, e.g. 104.2")
    init.add_argument("--carry", type=int, default=0)
    prices = commands.add_parser(
        "prices", help="Show newly fetched active Fantasy prices"
    )
    statistics = commands.add_parser(
        "statistics", help="Show the official Fantasy Statistics rankings"
    )
    clear_team = commands.add_parser(
        "clear-team",
        help="Remove the locally imported team (does not change your F1 account)",
    )
    recommend = commands.add_parser(
        "recommend", help="Recommend lineup, transfers and 2x Boost"
    )
    for command in (init, prices, recommend):
        command.add_argument(
            "--allow-old-prices",
            action="store_true",
            help="If the next roster is unpublished, preview with the latest complete official feed",
        )
    recommend.add_argument("--races", type=int, default=3)
    recommend.add_argument(
        "--no-telemetry",
        action="store_true",
        help="Use the results-only forecast for comparison",
    )
    recommend.add_argument(
        "--allow-penalties", action="store_true", help="Allow -10 per extra transfer"
    )
    backtest = commands.add_parser(
        "backtest", help="Evaluate historical regular and Sprint forecasts"
    )
    backtest.add_argument("--races", type=int, default=4)
    backtest.add_argument("--lookback", type=int, default=5)
    backtest.add_argument(
        "--show-points",
        action="store_true",
        help="Show predicted and actual points for every driver and constructor",
    )
    backtest.add_argument(
        "--compare-telemetry",
        action="store_true",
        help="Compare point errors with and without cached telemetry",
    )
    warm = commands.add_parser(
        "preload", help="Cache completed sessions for this season and the previous two"
    )
    warm.add_argument("--seasons", type=int, default=3)
    warm.add_argument("--refresh", action="store_true")
    warm.add_argument("--status", action="store_true")
    warm.add_argument("--year", type=int)
    warm.add_argument("--round", type=int)
    warm.add_argument("--session", help="Optional session name, e.g. Qualifying")
    for command in (init, prices, statistics, clear_team, recommend, backtest, warm):
        command.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format; JSON is a single machine-readable document",
        )
    return parser


def _json_output(
    command: str, data: dict, warnings: list[str] | None = None, status: str = "ok"
) -> None:
    print(
        json.dumps(
            envelope(command, data, warnings, status),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "clear-team":
            removed = args.state.exists() or args.state.is_symlink()
            if removed:
                args.state.unlink()
            if args.format == "json":
                _json_output(
                    "clear-team", {"state_path": str(args.state), "removed": removed}
                )
            else:
                print(
                    f"Removed locally imported team from {args.state}"
                    if removed
                    else f"No locally imported team at {args.state}"
                )
            return 0
        if args.command == "preload":
            if args.status:
                years = [
                    {"season": year, "processed_sessions": count}
                    for year, count in sorted(cache_status().items())
                ]
                if args.format == "json":
                    _json_output("preload", {"mode": "status", "years": years})
                else:
                    for item in years:
                        print(
                            f"{item['season']}: {item['processed_sessions']} processed sessions"
                        )
                return 0
            stored, skipped, gaps = preload(
                seasons=args.seasons,
                refresh=args.refresh,
                target_year=args.year,
                target_round=args.round,
                session_name=args.session,
            )
            if args.format == "json":
                _json_output(
                    "preload",
                    {
                        "mode": "run",
                        "seasons": args.seasons,
                        "processed": stored,
                        "reused": skipped,
                        "unavailable": gaps,
                    },
                    status="partial" if gaps else "ok",
                )
            else:
                print(
                    f"Processed {stored} sessions; reused {skipped}; unavailable {len(gaps)}"
                )
                for gap in gaps:
                    print(f"  {gap}")
            return 1 if gaps else 0
        if args.command == "statistics":
            stats = load_statistics(args.season)
            entries = [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind,
                    "price_tenths_m": s.price,
                    "season_points": s.season_points,
                }
                for s in stats.entries
            ]
            if args.format == "json":
                _json_output(
                    "statistics",
                    {
                        "season": stats.season,
                        "entries": entries,
                        "source": "https://fantasy.formula1.com/en/statistics",
                        "fetched_at": stats.fetched_at.isoformat(),
                    },
                )
            else:
                print(
                    f"F1 Fantasy Statistics — {stats.season} ({stats.fetched_at.isoformat()})"
                )
                for item in sorted(
                    entries, key=lambda e: (e["kind"], -e["season_points"])
                ):
                    print(
                        f"  {item['kind']:11} {item['id']:>6}  {item['name']:25} "
                        f"${item['price_tenths_m'] / 10:.1f}m  {item['season_points']:.1f} pts"
                    )
            return 0
        if args.command == "backtest":
            if not 1 <= args.races <= 24 or not 1 <= args.lookback <= 10:
                raise DataError("Backtest races must be 1–24 and lookback 1–10")
            rows = run_backtest(args.season, count=args.races, lookback=args.lookback)
            summaries = {}
            for sprint in (False, True):
                group = [r for r in rows if r.weekend.sprint == sprint]
                if group:
                    label = "sprint" if sprint else "regular"
                    drivers = sum(r.drivers for r in group)
                    constructors = sum(r.constructors for r in group)
                    summaries[label] = {
                        "weekends": len(group),
                        "drivers": drivers,
                        "constructors": constructors,
                        "driver_mae": sum(r.driver_error * r.drivers for r in group)
                        / drivers,
                        "constructor_mae": sum(
                            r.constructor_error * r.constructors for r in group
                        )
                        / constructors,
                    }
            comparison = {}
            if args.compare_telemetry:
                baseline = run_backtest(
                    args.season,
                    count=args.races,
                    lookback=args.lookback,
                    use_telemetry=False,
                )
                for label, is_sprint in (("regular", False), ("sprint", True)):
                    actual = [r for r in rows if r.weekend.sprint == is_sprint]
                    old = [r for r in baseline if r.weekend.sprint == is_sprint]
                    if actual:
                        comparison[label] = {
                            "baseline_driver_mae": sum(
                                r.driver_error * r.drivers for r in old
                            )
                            / sum(r.drivers for r in old),
                            "telemetry_driver_mae": summaries[label]["driver_mae"],
                            "weekends": len(actual),
                        }
            if args.format == "json":
                _json_output(
                    "backtest",
                    {
                        "season": args.season,
                        "lookback": args.lookback,
                        "rows": [backtest_row(r) for r in rows],
                        "summary": summaries,
                        "telemetry_comparison": comparison,
                        "mae_definition": "mean absolute predicted-minus-actual Fantasy points; session MAE includes drivers and constructors",
                    },
                )
                return 0
            for row in rows:
                label = "Sprint" if row.weekend.sprint else "regular"
                detail = (
                    f", Sprint {row.sprint_error:.1f}"
                    if row.sprint_error is not None
                    else ""
                )
                print(
                    f"{row.weekend.name} ({label}): MAE drivers {row.driver_error:.1f}, "
                    f"constructors {row.constructor_error:.1f}; "
                    f"qualifying {row.qualifying_error:.1f}{detail}, race {row.race_error:.1f}"
                )
                if args.show_points:
                    for kind in ("DRIVER", "CONSTRUCTOR"):
                        print(f"  {kind} points (predicted → actual; signed error):")
                        for item in row.assets:
                            if item.kind != kind:
                                continue
                            p, a = item.predicted, item.actual
                            print(
                                f"    {item.name} [{item.id}]: "
                                f"Q {p.qualifying:.1f}→{a.qualifying:.1f}, "
                                f"Sprint {p.sprint:.1f}→{a.sprint:.1f}, "
                                f"Race {p.race:.1f}→{a.race:.1f}; "
                                f"Total {p.total:.1f}→{a.total:.1f} ({item.error:+.1f})"
                            )
            for label, summary in summaries.items():
                display = "Sprint" if label == "sprint" else label
                print(
                    f"{display} ({summary['weekends']} weekends): driver MAE "
                    f"{summary['driver_mae']:.1f}; constructor MAE {summary['constructor_mae']:.1f}"
                )
            for label, item in comparison.items():
                display = "Sprint" if label == "sprint" else label
                print(
                    f"{display} telemetry comparison (driver MAE): "
                    f"{item['baseline_driver_mae']:.1f} baseline → "
                    f"{item['telemetry_driver_mae']:.1f} telemetry"
                )
            return 0
        if args.command == "recommend" and not 1 <= args.races <= 5:
            raise DataError("--races must be between 1 and 5")
        live, weekends = snapshot(args.season, allow_old_prices=args.allow_old_prices)
        warnings = []
        if live.provisional:
            warnings.append(
                f"PROVISIONAL: {live.weekend.name} has no published roster/prices. "
                f"Using {live.price_weekend.name}'s freshly retrieved feed; "
                "prices and availability for the next race are unverified."
            )
        if live.weekend.locked:
            warnings.append(
                "F1 Fantasy reports that the next race week is locked/not open."
            )
        if args.format == "text":
            print(
                f"Fantasy feed: {live.published_at.isoformat()} (fetched {live.fetched_at.isoformat()})"
            )
            for warning in warnings:
                print(warning)
        price_source = {
            "race_week": event_output(live.price_weekend or live.weekend),
            "published_at": live.published_at.isoformat(),
            "fetched_at": live.fetched_at.isoformat(),
            "provisional": live.provisional,
            "statistics_verified_at": (
                live.statistics.fetched_at.isoformat()
                if live.statistics is not None
                else None
            ),
        }
        if args.command == "prices":
            ordered = sorted(live.assets, key=lambda a: (a.kind, -a.price, a.name))
            if args.format == "json":
                _json_output(
                    "prices",
                    {
                        "event": event_output(live.weekend),
                        "price_source": price_source,
                        "assets": [asset_output(a) for a in ordered],
                    },
                    warnings,
                )
            else:
                print(f"{live.weekend.name}: {len(live.assets)} active assets")
                for item in ordered:
                    print(
                        f"  {item.kind:11} {item.id:>6}  {item.name:25} ${item.price / 10:.1f}m"
                    )
            return 0
        if args.command == "init":
            if args.import_file:
                state = _read_state(args.import_file)
            else:
                if not args.constructors or not args.budget:
                    raise DataError(
                        "--drivers also requires --constructors and --budget"
                    )
                state = {
                    "season": args.season,
                    "drivers": args.drivers,
                    "constructors": args.constructors,
                    "budget": args.budget,
                    "carry": args.carry,
                }
            chosen, budget, carry = _validate_state(state, live.assets, args.season)
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(state, indent=2) + "\n")
            if args.format == "json":
                _json_output(
                    "init",
                    {
                        "state_path": str(args.state),
                        "season": args.season,
                        "team_ids": sorted(chosen),
                        "budget_tenths_m": budget,
                        "carried_transfer": carry,
                        "price_source": price_source,
                    },
                    warnings,
                )
            else:
                print(f"Imported one team into {args.state}")
            return 0
        state = _read_state(args.state) if args.state.exists() else None
        if state is None:
            previous, budget, carry = None, 1000, 0
            if args.format == "text":
                print("Initial team: $100.0m budget, unlimited first-race changes")
        else:
            previous, budget, carry = _validate_state(state, live.assets, args.season)
        horizon = weekends[: args.races]
        forecasts = estimate_assets(
            live.assets, horizon, use_telemetry=not args.no_telemetry
        )
        lineups = optimize(
            live.assets,
            horizon,
            forecasts,
            budget,
            previous,
            carry,
            args.allow_penalties,
        )
        lineup_data = []
        for index, lineup in enumerate(lineups):
            selected = lineup.drivers + lineup.constructors
            qualifying = sum(forecasts[index, a.id].qualifying for a in selected)
            sprint = sum(forecasts[index, a.id].sprint for a in selected)
            race = sum(forecasts[index, a.id].race for a in selected)
            boost = forecasts[index, lineup.boost.id]
            before = (
                previous
                if index == 0
                else {
                    a.id
                    for a in lineups[index - 1].drivers
                    + lineups[index - 1].constructors
                }
            )
            after = {a.id for a in selected}
            transfers = {
                "net": int(lineup.transfers),
                "penalty_points": int(lineup.transfer_penalty),
                "out_ids": sorted(before - after) if before is not None else [],
                "in_ids": sorted(after - before) if before is not None else [],
            }
            lineup_data.append(
                {
                    "event": event_output(lineup.weekend),
                    "drivers": [asset_output(a) for a in lineup.drivers],
                    "constructors": [asset_output(a) for a in lineup.constructors],
                    "boost_driver_id": lineup.boost.id,
                    "cost_tenths_m": int(lineup.cost),
                    "expected_points": float(lineup.expected_points),
                    "session_points_including_boost": {
                        "qualifying": float(qualifying + boost.qualifying),
                        "sprint": float(sprint + boost.sprint),
                        "race": float(race + boost.race),
                    },
                    "transfers": transfers,
                }
            )
            if args.format == "json":
                continue
            print(
                f"\n{lineup.weekend.name} ({'Sprint' if lineup.weekend.sprint else 'regular'}) — "
                f"first scoring session {lineup.weekend.first_session.isoformat()}"
            )
            print(f"  Drivers: {', '.join(a.name for a in lineup.drivers)}")
            print(f"  Constructors: {', '.join(a.name for a in lineup.constructors)}")
            print(f"  2x Boost: {lineup.boost.name}")
            print(
                f"  Cost: ${lineup.cost / 10:.1f}m / ${budget / 10:.1f}m; projected: {lineup.expected_points:.1f} pts"
            )
            print(
                f"  Sessions (including 2x Boost): qualifying {qualifying + boost.qualifying:.1f}, "
                f"Sprint {sprint + boost.sprint:.1f}, race {race + boost.race:.1f}"
            )
            if previous is not None or index:
                print(
                    f"  Net transfers: {lineup.transfers}; penalty: -{lineup.transfer_penalty} pts"
                )
                names = {a.id: a.name for a in live.assets}
                print(
                    f"  Out: {', '.join(names[id_] for id_ in transfers['out_ids']) or 'none'}"
                )
                print(
                    f"  In: {', '.join(names[id_] for id_ in transfers['in_ids']) or 'none'}"
                )
        if args.format == "json":
            _json_output(
                "recommend",
                {
                    "season": args.season,
                    "price_source": price_source,
                    "current_team_imported": previous is not None,
                    "budget_tenths_m": budget,
                    "carried_transfer": carry,
                    "telemetry_enabled": not args.no_telemetry,
                    "lineups": lineup_data,
                    "projected_total_points": float(
                        sum(l.expected_points for l in lineups)
                    ),
                    "future_prices_assumed_constant": True,
                },
                warnings,
            )
            return 0
        print(
            f"\nProjected {len(lineups)}-race total: {sum(l.expected_points for l in lineups):.1f} pts"
        )
        print(
            "Fantasy lock time must be checked in the game. Forecast uses current-season official scoring and prior visits to each circuit; future prices held constant. Re-import your actual team after making changes."
        )
        if live.provisional:
            print(
                "PROVISIONAL ONLY: Re-run without --allow-old-prices before applying this team."
            )
        return 0
    except (DataError, OSError, ValueError) as exc:
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": args.command,
                        "status": "error",
                        "error": {"code": type(exc).__name__, "message": str(exc)},
                    }
                ),
                file=sys.stderr,
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
