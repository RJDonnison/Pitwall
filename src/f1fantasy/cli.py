"""Fantasy recommendations and explicit one-team account actions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .backtest import run_backtest
from .chips import CHIPS, PREWEEK_CHIPS, final_fix, load_chip_values
from .data import DataError, load_statistics, snapshot
from .history import cache_status, preload
from .optimizer import Lineup, optimize
from .output import asset as asset_output
from .output import backtest_row, envelope, event as event_output
from .projections import Estimate, estimate_assets

DEFAULT_STATE = Path(".f1fantasy/team.json")
DEFAULT_ACCOUNT = (
    Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    / "f1fantasy/account"
)
# Explicit heuristic opportunity costs, not fitted chip forecasts.
DEFAULT_RESERVE = {
    "autopilot": 15.0,
    "x3": 40.0,
    "no_negative": 25.0,
    "wildcard": 20.0,
    "limitless": 80.0,
}


def _planning_options(parser):
    parser.add_argument("--races", type=int, default=3)
    parser.add_argument("--no-telemetry", action="store_true")
    parser.add_argument("--no-risk", action="store_true")
    parser.add_argument("--allow-penalties", action="store_true")
    parser.add_argument(
        "--chips",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use remaining chip inventory (default: enabled)",
    )
    parser.add_argument(
        "--chip",
        choices=sorted(PREWEEK_CHIPS),
        help="Force this chip on the first planned race",
    )
    parser.add_argument(
        "--chip-reserve",
        action="append",
        default=[],
        metavar="CHIP=POINTS",
        help="Opportunity cost of spending instead of saving beyond the horizon",
    )


def _plan(args, live, weekends, state):
    """Shared fresh forecast path for recommendations and explicit apply."""
    if not 1 <= args.races <= 5:
        raise DataError("--races must be between 1 and 5")
    if state is None:
        previous, budget, carry = None, 1000, 0
    else:
        previous, budget, carry = _validate_state(state, live.assets, args.season)
        if "baseline_ids" in state:
            previous = frozenset(str(id_) for id_ in state["baseline_ids"])
        if state.get("active_chip") == "final_fix":
            raise DataError(
                "Final Fix has already been used; inspect account show for retained and remaining scoring"
            )
        if state.get("unlimited_transfers") and state.get("active_chip") not in {
            "wildcard",
            "limitless",
        }:
            previous, carry = None, 0
    horizon = weekends[: args.races]
    active = state.get("active_chip") if state else None
    restoration = (
        frozenset(state["limitless_restoration_ids"])
        if active == "limitless" and state.get("limitless_restoration_ids")
        else None
    )
    current_ids = (
        frozenset(str(i) for i in state["drivers"] + state["constructors"])
        if state
        else None
    )
    if active == "limitless" and restoration is None:
        # The temporary team is known, but a pre-activation restoration draft is
        # not reliably exposed. Never invent a durable roster for future rounds.
        horizon = horizon[:1]
    forecasts = estimate_assets(
        live.assets,
        horizon,
        use_telemetry=not args.no_telemetry,
        use_risk=not args.no_risk,
    )
    enabled = args.chips or args.chip is not None
    available = (
        frozenset(state.get("available_chips", []))
        if enabled and state
        else frozenset()
    )
    if enabled and (state is None or "available_chips" not in state):
        raise DataError(
            "Chip planning needs remaining available_chips inventory in an import or recommend --account"
        )
    if not available <= CHIPS:
        raise DataError("Unknown chip in remaining inventory")
    reserve = dict(DEFAULT_RESERVE)
    if len(weekends) <= args.races:
        reserve = {name: 0.0 for name in reserve}
    reserve.update(state.get("chip_reserve", {}) if state else {})
    for item in args.chip_reserve:
        try:
            name, value = item.split("=", 1)
            reserve[name] = float(value)
        except ValueError as exc:
            raise DataError("Use --chip-reserve CHIP=POINTS") from exc
    # Local imports must explicitly attest first-weekend eligibility; remote
    # state carries the official selected team's eligible inventory.
    eligibility = {}
    for index, weekend in enumerate(horizon):
        names = available & PREWEEK_CHIPS
        if index == 0:
            if state and "eligible_chips" in state:
                names &= frozenset(state["eligible_chips"])
            elif not state or state.get("completed_first_weekend") is not True:
                names -= {"limitless", "wildcard"}
        eligibility[index] = names
    if active:
        eligibility[0] = frozenset({active})
    empirical = any(
        names & {"autopilot", "no_negative"} for names in eligibility.values()
    )
    values = load_chip_values(live.assets, horizon, forecasts) if empirical else None
    lineups = optimize(
        live.assets,
        horizon,
        forecasts,
        budget,
        previous,
        carry,
        args.allow_penalties,
        available_chips=available,
        eligible_chips=eligibility,
        chip_values=values,
        chip_reserve=reserve,
        forced_chip=args.chip,
        active_chip=active,
        limitless_restore=restoration if active == "limitless" else current_ids,
    )
    history = (
        {
            "sample_gamedays": values.history_gamedays,
            "skipped_null_score_gamedays": values.skipped_history_gamedays,
        }
        if values is not None
        else None
    )
    return (
        lineups,
        forecasts,
        previous,
        budget,
        carry,
        reserve if enabled else {},
        history,
    )


def _account_command(args):
    from . import account

    directory = args.account_dir
    action = args.account_action
    if action == "connect":
        if args.format == "text":
            print(
                "Sign in and complete MFA in the dedicated browser, then open My Team.",
                file=sys.stderr,
            )
        result = account.connect(directory, args.season, args.team, args.timeout)
    elif action == "show":
        result = account.show(directory, args.season)
    elif action == "audit":
        result = {"entries": account.audit(directory)}
    else:
        recovered = (
            account.recover(directory, args.season, confirm_completed=False)
            if args.replan or args.final_fix
            else account.recover(directory, args.season)
        )
        if recovered is not None:
            if args.format == "json":
                _json_output("account apply", recovered)
            else:
                print(json.dumps(recovered, indent=2))
            return 0
        if args.final_fix:
            result, proposal = _account_final_fix(args)
            if proposal is not None:
                result = account.apply_final_fix(directory, args.season, proposal)
            if args.format == "json":
                _json_output("account apply", result)
            else:
                print(json.dumps(result, indent=2))
            return 0
        state = account.show(directory, args.season)
        live, weekends = snapshot(args.season)
        if state["gameday_id"] != live.weekend.gameday_id:
            raise DataError(
                "Account event differs from the freshly fetched planning event"
            )
        lineups, _, previous, budget, _, _, _ = _plan(args, live, weekends, state)
        first = lineups[0]
        proposal = {
            "season": args.season,
            "gameday_id": first.weekend.gameday_id,
            "drivers": [a.id for a in first.drivers],
            "constructors": [a.id for a in first.constructors],
            "boost_driver_id": first.boost.id,
            "chip": first.chip,
            "x3_driver_id": first.x3.id if first.x3 else None,
            "budget_tenths_m": budget,
            "baseline_ids": state["baseline_ids"],
            "expected_transfer_penalty": first.transfer_penalty,
        }
        result = account.apply(directory, args.season, proposal, args.allow_penalties)
    if args.format == "json":
        _json_output("account " + action, result)
    else:
        print(json.dumps(result, indent=2))
    return 0


def _chips_command(args):
    if args.final_fix is True and not args.account:
        raise DataError(
            "Use chips --final-fix with the connected account, or supply a provisional input file with --no-account"
        )
    if args.final_fix and args.account:
        result, _ = _account_final_fix(args)
        if args.format == "json":
            _json_output("chips", result)
        else:
            print(json.dumps(result, indent=2))
        return 0
    if args.account:
        from . import account

        state = account.show(args.account_dir, args.season)
    else:
        state = _read_state(args.state) if args.state.exists() else {}
    if args.final_fix:
        result = _final_fix_preview(args, state)
    else:
        available = state.get("available_chips")
        if available is not None and (
            not isinstance(available, list) or not set(available) <= CHIPS
        ):
            raise DataError("Invalid remaining chip inventory")
        result = {
            "inventory_verified": args.account,
            "available_chips": available,
            "eligible_chips": state.get("eligible_chips"),
            "reserve_points": dict(DEFAULT_RESERVE, **state.get("chip_reserve", {})),
            "rules": {
                "one_per_weekend": True,
                "once_per_season": True,
                "final_fix": "separate remaining-session-only decision",
            },
        }
    if args.format == "json":
        _json_output("chips", result)
    else:
        print(json.dumps(result, indent=2))
    return 0


def _account_final_fix(args):
    """Forecast only still-unscored sessions using a server-verified account window."""
    from . import account

    context = account.final_fix_context(args.account_dir, args.season)
    state, assets, weekend = context["state"], context["assets"], context["weekend"]
    if not context["eligible"]:
        raise DataError("Final Fix is not eligible in the authoritative server window")
    forecasts = estimate_assets(
        assets,
        [weekend],
        use_telemetry=not getattr(args, "no_telemetry", False),
        use_risk=not getattr(args, "no_risk", False),
    )
    sessions = context["remaining_sessions"]
    if not sessions or not set(sessions) <= {"sprint", "race"}:
        raise DataError("Unverified Final Fix remaining-session boundary")
    remaining = {
        a.id: Estimate(
            0,
            forecasts[0, a.id].sprint if "sprint" in sessions else 0,
            forecasts[0, a.id].race if "race" in sessions else 0,
        )
        for a in assets
    }
    catalog = {a.id: a for a in assets}
    drivers = tuple(catalog[i] for i in state["drivers"])
    constructors = tuple(catalog[i] for i in state["constructors"])
    original = Lineup(
        weekend,
        drivers,
        constructors,
        catalog[state["boost_driver_id"]],
        sum(a.price for a in drivers + constructors),
        0,
        0,
        state["transfer_penalty"],
    )
    decision = final_fix(
        original,
        assets,
        remaining,
        state["budget_tenths_m"],
        available="final_fix" in state["available_chips"],
        eligible=context["eligible"],
        accrued_points=context["accrued_points"],
    )
    result = {
        "provisional": False,
        "inventory_verified": True,
        "window": context["window"],
        "remaining_sessions": sessions,
        "out_id": decision.outgoing.id if decision.outgoing else None,
        "in_id": decision.incoming.id if decision.incoming else None,
        "boost_driver_id": decision.boost.id,
        "accrued_points": decision.accrued_points,
        "remaining_points": decision.remaining_points.total,
        "expected_total_points": decision.expected_points - state["transfer_penalty"],
        "original_roster_restored_after_weekend": True,
    }
    if decision.outgoing is None:
        return dict(result, apply_status="unchanged"), None
    proposal = {
        "season": args.season,
        "gameday_id": weekend.gameday_id,
        "drivers": [a.id for a in decision.drivers],
        "constructors": [a.id for a in decision.constructors],
        "boost_driver_id": decision.boost.id,
        "chip": "final_fix",
        "x3_driver_id": None,
        "budget_tenths_m": state["budget_tenths_m"],
        "baseline_ids": state["baseline_ids"],
        "expected_transfer_penalty": state["transfer_penalty"],
        "outgoing_id": decision.outgoing.id,
        "incoming_id": decision.incoming.id,
        "original_ids": state["drivers"] + state["constructors"],
        "original_boost_driver_id": state["boost_driver_id"],
        "window": context["window"],
        "retained_points": state["retained_points"],
    }
    return result, proposal


def _final_fix_preview(args, state):
    """Explicit what-if preview; never substitutes a user window for remote authority."""
    from .data import season_weekends, load_assets, load_statistics

    spec = _read_state(args.final_fix)
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(spec["window_open_utc"])
    end = datetime.fromisoformat(spec["window_close_utc"])
    if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
        raise DataError(
            "Final Fix preview requires an explicit currently open timezone-aware window"
        )
    weekend = next(
        (w for w in season_weekends(args.season) if w.gameday_id == spec["gameday_id"]),
        None,
    )
    if weekend is None:
        raise DataError("Unknown Final Fix event")
    assets, _ = load_assets(weekend.gameday_id)
    load_statistics(args.season, assets)
    _, budget, _ = _validate_state(state, assets, args.season)
    known = {a.id: a for a in assets}
    drivers = tuple(known[str(id_)] for id_ in state["drivers"])
    constructors = tuple(known[str(id_)] for id_ in state["constructors"])
    boost = known[str(state["boost_driver_id"])]
    original = Lineup(
        weekend,
        drivers,
        constructors,
        boost,
        sum(a.price for a in drivers + constructors),
        0,
        0,
        0,
        state.get("active_chip"),
    )
    remaining = {
        id_: Estimate(**points) for id_, points in spec["remaining_points"].items()
    }
    sessions = spec["remaining_sessions"]
    if (
        not isinstance(sessions, list)
        or not sessions
        or not set(sessions) <= {"sprint", "race"}
    ):
        raise DataError(
            "Final Fix remaining_sessions must explicitly list only unscored Sprint/race sessions"
        )
    if any(
        p.qualifying != 0
        or ("sprint" not in sessions and p.sprint != 0)
        or ("race" not in sessions and p.race != 0)
        for p in remaining.values()
    ):
        raise DataError("Final Fix input includes an elapsed session")
    decision = final_fix(
        original,
        assets,
        remaining,
        budget,
        available="final_fix" in state.get("available_chips", []),
        eligible=True,
        accrued_points=float(spec["accrued_points"]),
    )
    return {
        "provisional": True,
        "window_source": "user_supplied_not_account_verified",
        "remaining_sessions": sessions,
        "out_id": decision.outgoing.id if decision.outgoing else None,
        "in_id": decision.incoming.id if decision.incoming else None,
        "boost_driver_id": decision.boost.id,
        "accrued_points": decision.accrued_points,
        "remaining_expected_points": decision.remaining_points.total,
        "expected_total_points": decision.expected_points,
        "original_team_restored_after_weekend": True,
    }


class CLIParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DataError(message)


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
        if (
            state.get("active_chip") != "limitless"
            and sum(catalog[id_].price for id_ in chosen) > budget
        ):
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
    parser = CLIParser(
        description="F1 Fantasy team planner and manual account management"
    )
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--account-dir", type=Path, default=DEFAULT_ACCOUNT)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=CLIParser
    )
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
    recommend.add_argument(
        "--account",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh the connected account team (default: enabled)",
    )
    chips = commands.add_parser(
        "chips", help="Show remaining chips, reserves and Final Fix previews"
    )
    chips.add_argument(
        "--account",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh the connected account team (default: enabled)",
    )
    chips.add_argument(
        "--final-fix",
        type=Path,
        nargs="?",
        const=True,
        help="Preview account-aware Final Fix; optional PATH with --no-account provides provisional inputs",
    )
    account = commands.add_parser(
        "account", help="Manage one explicitly connected account team"
    )
    actions = account.add_subparsers(
        dest="account_action", required=True, parser_class=CLIParser
    )
    connect = actions.add_parser(
        "connect", help="Sign in manually using a persistent private browser"
    )
    connect.add_argument("--team", type=int, choices=(1, 2, 3), required=True)
    connect.add_argument("--timeout", type=int, default=300)
    show = actions.add_parser("show", help="Read fresh selected-team state")
    apply = actions.add_parser(
        "apply",
        help="Reforecast, submit one team's next lineup and verify live read-back",
    )
    apply.add_argument(
        "--final-fix",
        action="store_true",
        help="Re-evaluate only remaining sessions in the verified post-qualifying window",
    )
    apply.add_argument(
        "--replan",
        action="store_true",
        help="Generate a new plan instead of confirming a completed chip apply; pending recovery still runs first",
    )
    audit = actions.add_parser("audit", help="Show durable apply outcomes offline")
    _planning_options(recommend)
    _planning_options(apply)
    for command in (init, prices, recommend):
        command.add_argument(
            "--allow-old-prices",
            action="store_true",
            help="If the next roster is unpublished, preview with the latest complete official feed",
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
    backtest.add_argument(
        "--compare-risk",
        action="store_true",
        help="Compare driver race-point errors with and without risk adjustment",
    )
    backtest.add_argument(
        "--no-risk",
        action="store_true",
        help="Backtest the original race/Sprint averaging model",
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
    for command in (
        init,
        prices,
        statistics,
        clear_team,
        recommend,
        backtest,
        warm,
        chips,
        connect,
        show,
        apply,
        audit,
    ):
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
    raw = sys.argv[1:] if argv is None else argv
    try:
        args = _parser().parse_args(raw)
    except DataError as exc:
        json_mode = any(
            raw[index : index + 2] == ["--format", "json"]
            for index in range(len(raw) - 1)
        )
        if json_mode:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "error": {"code": "invalid_arguments", "message": str(exc)},
                    }
                ),
                file=sys.stderr,
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "account":
            return _account_command(args)
        if args.command == "chips":
            return _chips_command(args)
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
            rows = run_backtest(
                args.season,
                count=args.races,
                lookback=args.lookback,
                use_risk=not args.no_risk,
            )
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
                    use_risk=not args.no_risk,
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
            risk_comparison = {}
            if args.compare_risk:
                old_rows = run_backtest(
                    args.season,
                    count=args.races,
                    lookback=args.lookback,
                    use_risk=False,
                )
                new_rows = (
                    rows
                    if not args.no_risk
                    else run_backtest(
                        args.season, count=args.races, lookback=args.lookback
                    )
                )

                def driver_race_mae(group):
                    errors = [
                        abs(item.predicted.race - item.actual.race)
                        for row in group
                        for item in row.assets
                        if item.kind == "DRIVER"
                    ]
                    return sum(errors) / len(errors)

                for label, sprint in (("regular", False), ("sprint", True)):
                    old = [row for row in old_rows if row.weekend.sprint == sprint]
                    new = [row for row in new_rows if row.weekend.sprint == sprint]
                    if old and new:
                        risk_comparison[label] = {
                            "weekends": len(old),
                            "baseline_driver_race_mae": driver_race_mae(old),
                            "risk_driver_race_mae": driver_race_mae(new),
                        }
                        if sprint:

                            def sprint_mae(group):
                                errors = [
                                    abs(item.predicted.sprint - item.actual.sprint)
                                    for row in group
                                    for item in row.assets
                                    if item.kind == "DRIVER"
                                ]
                                return sum(errors) / len(errors)

                            risk_comparison[label]["baseline_driver_sprint_mae"] = (
                                sprint_mae(old)
                            )
                            risk_comparison[label]["risk_driver_sprint_mae"] = (
                                sprint_mae(new)
                            )
            if args.format == "json":
                _json_output(
                    "backtest",
                    {
                        "season": args.season,
                        "lookback": args.lookback,
                        "risk_model_enabled": not args.no_risk,
                        "rows": [backtest_row(r) for r in rows],
                        "summary": summaries,
                        "telemetry_comparison": comparison,
                        "risk_comparison": risk_comparison,
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
                bias = f"Q {row.qualifying_bias:+.1f}, race {row.race_bias:+.1f}"
                if row.sprint_bias is not None:
                    bias += f", Sprint {row.sprint_bias:+.1f}"
                print(f"  Signed bias (predicted − actual): {bias}")
                if row.baseline_driver_race_error is not None:
                    print(
                        f"  Driver race MAE vs last-3 average ({row.baseline_driver_count} drivers): "
                        f"model {row.model_driver_race_error_on_baseline:.1f}, "
                        f"naive {row.baseline_driver_race_error:.1f}"
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
            for label, item in risk_comparison.items():
                display = "Sprint" if label == "sprint" else label
                print(
                    f"{display} race-risk comparison (driver race MAE): "
                    f"{item['baseline_driver_race_mae']:.1f} baseline → "
                    f"{item['risk_driver_race_mae']:.1f} risk-adjusted"
                )
                if label == "sprint":
                    print(
                        f"Sprint-risk comparison (driver Sprint MAE): "
                        f"{item['baseline_driver_sprint_mae']:.1f} baseline → "
                        f"{item['risk_driver_sprint_mae']:.1f} risk-adjusted"
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
        if args.account:
            from . import account

            state = account.show(args.account_dir, args.season)
            if state["gameday_id"] != live.weekend.gameday_id:
                raise DataError("Account event differs from the planning event")
        else:
            state = _read_state(args.state) if args.state.exists() else None
        lineups, forecasts, previous, budget, carry, reserves, chip_history = _plan(
            args, live, weekends, state
        )
        if state is None and args.format == "text":
            print("Initial team: $100.0m budget, unlimited first-race changes")
        if reserves:
            warnings.append(
                "Chip reserve points are explicit heuristic opportunity costs beyond the horizon; empirical Autopilot/No Negative forecasts are small-sample approximations."
            )
            if args.format == "text":
                print(warnings[-1])
                print(
                    "Chip saving costs (points): "
                    + ", ".join(f"{name}={value:g}" for name, value in reserves.items())
                )
        if chip_history is not None:
            coverage = "Chip history samples per planned weekend: " + ", ".join(
                str(len(ids)) for ids in chip_history["sample_gamedays"].values()
            )
            if chip_history["skipped_null_score_gamedays"]:
                coverage += "; excluded official null-score game days: " + ", ".join(
                    str(id_) for id_ in chip_history["skipped_null_score_gamedays"]
                )
            warnings.append(coverage)
            if args.format == "text":
                print(coverage)
        lineup_data = []
        if (
            state
            and state.get("active_chip") == "limitless"
            and not state.get("limitless_restoration_ids")
        ):
            message = "Active Limitless: planning this weekend only; restoration draft is not exposed, so future-round transfers are not inferred."
            warnings.append(message)
            if args.format == "text":
                print(message)
        for index, lineup in enumerate(lineups):
            selected = lineup.drivers + lineup.constructors
            session = lineup.session_points
            before = previous
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
                    "chip": lineup.chip,
                    "x3_driver_id": lineup.x3.id if lineup.x3 else None,
                    "cost_tenths_m": int(lineup.cost),
                    "expected_points": float(lineup.expected_points),
                    "session_points_including_boost": {
                        "qualifying": float(session.qualifying),
                        "sprint": float(session.sprint),
                        "race": float(session.race),
                    },
                    "transfers": transfers,
                }
            )
            if lineup.chip != "limitless":
                previous = frozenset(after)
            elif index == 0 and state:
                previous = frozenset(
                    state.get(
                        "limitless_restoration_ids",
                        state["drivers"] + state["constructors"],
                    )
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
            if lineup.chip:
                print(
                    f"  Chip: {lineup.chip}"
                    + (f"; 3x Boost: {lineup.x3.name}" if lineup.x3 else "")
                )
            print(
                f"  Cost: ${lineup.cost / 10:.1f}m / ${budget / 10:.1f}m; projected: {lineup.expected_points:.1f} pts"
            )
            print(
                f"  Sessions (including Boost/chip): qualifying {session.qualifying:.1f}, "
                f"Sprint {session.sprint:.1f}, race {session.race:.1f}"
            )
            if before is not None:
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
                    "current_team_imported": state is not None,
                    "account_synced": args.account,
                    "chip_reserve_points": reserves,
                    "chip_history": chip_history,
                    "budget_tenths_m": budget,
                    "carried_transfer": carry,
                    "telemetry_enabled": not args.no_telemetry,
                    "risk_model_enabled": not args.no_risk,
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
    except (DataError, OSError, ValueError, KeyError, TypeError) as exc:
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
