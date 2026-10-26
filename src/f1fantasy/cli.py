"""Read-only F1 Fantasy command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .data import DataError, snapshot
from .optimizer import optimize
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
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"Cannot read team state {path}: {exc}") from exc


def _validate_state(
    state: dict, assets: tuple, season: int
) -> tuple[frozenset[str], int, int]:
    try:
        if int(state["season"]) != season:
            raise DataError("Team season differs from live Fantasy season")
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
                "Imported team exceeds the provided current budget at live prices"
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
    commands.add_parser("prices", help="Show newly fetched active Fantasy prices")
    recommend = commands.add_parser(
        "recommend", help="Recommend lineup, transfers and 2x Boost"
    )
    recommend.add_argument("--races", type=int, default=3)
    recommend.add_argument(
        "--allow-penalties", action="store_true", help="Allow -10 per extra transfer"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "recommend" and not 1 <= args.races <= 5:
            raise DataError("--races must be between 1 and 5")
        live, weekends = snapshot(args.season)
        print(
            f"Fantasy feed: {live.published_at.isoformat()} (fetched {live.fetched_at.isoformat()})"
        )
        if args.command == "prices":
            print(f"{live.weekend.name}: {len(live.assets)} active assets")
            for asset in sorted(live.assets, key=lambda a: (a.kind, -a.price, a.name)):
                print(
                    f"  {asset.kind:11} {asset.id:>6}  {asset.name:25} ${asset.price / 10:.1f}m"
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
            _validate_state(state, live.assets, args.season)
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(state, indent=2) + "\n")
            print(f"Imported one team into {args.state}")
            return 0
        state = _read_state(args.state) if args.state.exists() else None
        if state is None:
            previous, budget, carry = None, 1000, 0
            print("Initial team: $100.0m budget, unlimited first-race changes")
        else:
            previous, budget, carry = _validate_state(state, live.assets, args.season)
        horizon = weekends[: args.races]
        forecasts = estimate_assets(live.assets, horizon)
        lineups = optimize(
            live.assets,
            horizon,
            forecasts,
            budget,
            previous,
            carry,
            args.allow_penalties,
        )
        for index, lineup in enumerate(lineups):
            print(
                f"\n{lineup.weekend.name} ({'Sprint' if lineup.weekend.sprint else 'regular'}) — {lineup.weekend.first_session.isoformat()}"
            )
            print(f"  Drivers: {', '.join(a.name for a in lineup.drivers)}")
            print(f"  Constructors: {', '.join(a.name for a in lineup.constructors)}")
            print(f"  2x Boost: {lineup.boost.name}")
            print(
                f"  Cost: ${lineup.cost / 10:.1f}m / ${budget / 10:.1f}m; projected: {lineup.expected_points:.1f} pts"
            )
            if previous is not None or index:
                print(
                    f"  Net transfers: {lineup.transfers}; penalty: -{lineup.transfer_penalty} pts"
                )
                before = (
                    previous
                    if index == 0
                    else {
                        a.id
                        for a in lineups[index - 1].drivers
                        + lineups[index - 1].constructors
                    }
                )
                after = {a.id for a in lineup.drivers + lineup.constructors}
                names = {a.id: a.name for a in live.assets}
                print(
                    f"  Out: {', '.join(names[id_] for id_ in sorted(before - after)) or 'none'}"
                )
                print(
                    f"  In: {', '.join(names[id_] for id_ in sorted(after - before)) or 'none'}"
                )
            if lineup.weekend.sprint:
                print("  Sprint included in projected driver and constructor points")
        print(
            "\nForecast omits overtakes, Driver of the Day and pit-stop bonuses; future prices held constant. Re-import your actual team after making changes."
        )
        return 0
    except (DataError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
