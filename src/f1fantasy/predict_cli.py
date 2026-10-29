"""Predict command tree and its independent unattended lifecycle."""

import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from . import (
    account as security,
    predict,
    predict_account,
    predict_data,
    predict_scheduler,
)
from .data import DataError


def register(commands):
    parser = commands.add_parser(
        "predict",
        help="Official F1 Predict questions, expected points and verified answer submission",
    )
    actions = parser.add_subparsers(dest="predict_action", required=True)
    leaves = []

    def target(p):
        p.add_argument("--gameday", type=int)
        p.add_argument("--scope", choices=("round", "season"), default="round")

    def model(p):
        p.add_argument("--simulations", type=int, default=4000)
        p.add_argument("--seed", type=int, default=2026)
        p.add_argument("--no-telemetry", action="store_true")

    for name in ("questions", "recommend"):
        p = actions.add_parser(name)
        target(p)
        if name == "recommend":
            model(p)
            p.add_argument(
                "--archive", action=argparse.BooleanOptionalAction, default=True
            )
        leaves.append(p)
    for name in ("settle", "backtest"):
        leaves.append(actions.add_parser(name))
    account = actions.add_parser("account").add_subparsers(
        dest="predict_account_action", required=True
    )
    connect = account.add_parser("connect")
    connect.add_argument("--timeout", type=int, default=300)
    leaves.append(connect)
    for name in ("show", "apply", "audit"):
        p = account.add_parser(name)
        if name != "audit":
            target(p)
        if name == "apply":
            model(p)
        leaves.append(p)
    daemon = actions.add_parser("daemon").add_subparsers(
        dest="predict_daemon_action", required=True
    )
    run = daemon.add_parser("run")
    model(run)
    run.add_argument("--scope", choices=("round", "season"), default="round")
    run.add_argument("--early-hours", type=float, default=24)
    run.add_argument("--final-minutes", type=float, default=15)
    run.add_argument("--safety-seconds", type=float, default=90)
    run.add_argument("--poll-seconds", type=float, default=60)
    run.add_argument(
        "--once", action="store_true", help="Run one real potentially submitting cycle"
    )
    run.add_argument("--notify-command", type=Path)
    leaves.append(run)
    for name in ("status", "audit", "retry", "cancel"):
        p = daemon.add_parser(name)
        if name in {"retry", "cancel"}:
            p.add_argument("job_id")
        leaves.append(p)
    return leaves


def _emit(args, result, *, complete=True):
    from .cli import _json_output

    command = "predict " + args.predict_action
    if args.format == "json":
        _json_output(command, result, status="ok" if complete else "partial")
    elif args.predict_action == "recommend":
        print(
            f"Predict {result['season']} / {result['scope']} {result['gameday_id']}: expected {result['expected_total_points']:.1f} points"
        )
        for row in result["answers"]:
            print(
                f"  {row['question_id']} {row['text']}: {', '.join(row['selected_names'])} {'[2x]' if row['booster_id'] == '1' else ''} — {row['expected_points']:.1f} expected pts"
            )
        for row in result["unsupported"]:
            print(f"  UNSUPPORTED {row['question_id']}: {row['reason']}")
        print("No answers submitted. Partial forecasts cannot be applied.")
        for warning in result["warnings"]:
            print(warning)
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if complete else 1


def _recommend(args, snapshot):
    if not 100 <= args.simulations <= 100000:
        raise DataError("Predict --simulations must be between 100 and 100000")
    return predict.recommend(
        snapshot,
        directory=args.account_dir if getattr(args, "archive", True) else None,
        simulations=args.simulations,
        seed=args.seed,
        use_telemetry=not args.no_telemetry,
    )


def _daemon(args):
    action = args.predict_daemon_action
    if action != "run":
        if action == "status":
            result = predict_scheduler.status(args.account_dir)
        elif action == "audit":
            result = {"events": predict_scheduler.audit(args.account_dir)}
        else:
            result = getattr(predict_scheduler, action)(args.account_dir, args.job_id)
        return _emit(args, result)
    if not math.isfinite(args.poll_seconds) or args.poll_seconds <= 0:
        raise DataError("Predict poll seconds must be finite and positive")
    policy = {
        k: getattr(args, k)
        for k in ("early_hours", "final_minutes", "safety_seconds", "scope")
    }
    predict_scheduler.validate(policy)
    stop = threading.Event()
    handlers = {}
    old_headless = os.environ.get("F1FANTASY_HEADLESS")

    def notify(event):
        payload = json.dumps(event, allow_nan=False)
        print(payload, file=sys.stderr, flush=True)
        if args.notify_command:
            subprocess.run(
                [str(args.notify_command)],
                input=payload,
                text=True,
                timeout=15,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            handlers[sig] = signal.signal(sig, lambda *_: stop.set())
        os.environ["F1FANTASY_HEADLESS"] = "1"
        with security._locked(
            predict_account.storage_directory(args.account_dir) / "scheduler" / "runner"
        ):
            while not stop.is_set():
                try:
                    predict.settle(args.account_dir)
                except (DataError, OSError):
                    # Historical-label availability does not redefine the live
                    # write contract. Forecast metadata reports calibration gaps.
                    print(
                        ' {"kind":"predict_calibration_unavailable"}', file=sys.stderr
                    )
                result = predict_scheduler.tick(
                    args.account_dir,
                    args.season,
                    policy,
                    lambda snapshot: _recommend(args, snapshot),
                    notify=notify,
                )
                if args.once:
                    _emit(args, result)
                    return 1 if result.get("status") == "blocked" else 0
                stop.wait(args.poll_seconds)
        return 0
    finally:
        if old_headless is None:
            os.environ.pop("F1FANTASY_HEADLESS", None)
        else:
            os.environ["F1FANTASY_HEADLESS"] = old_headless
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def command(args):
    action = args.predict_action
    if action == "daemon":
        return _daemon(args)
    if action == "backtest":
        return _emit(args, predict.backtest(args.account_dir))
    if action == "settle":
        return _emit(args, predict.settle(args.account_dir))
    if action == "questions":
        return _emit(args, predict_data.fetch(args.season, args.gameday, args.scope))
    if action == "recommend":
        result = _recommend(
            args, predict_data.fetch(args.season, args.gameday, args.scope)
        )
        return _emit(args, result, complete=result["complete"])
    action = args.predict_account_action
    if action == "connect":
        result = predict_account.connect(args.account_dir, args.season, args.timeout)
    elif action == "audit":
        result = {"entries": predict_account.audit(args.account_dir)}
    elif action == "show":
        result = predict_account.show(
            args.account_dir, args.season, args.gameday, args.scope
        )
    else:
        result = predict_account.recover(
            args.account_dir, args.season, args.gameday, args.scope
        )
        if result.get("apply_status") == "nothing_to_recover":
            current = result
            recommendation = _recommend(args, current)
            if not recommendation["complete"]:
                return _emit(args, recommendation, complete=False)
            result = predict_account.apply(
                args.account_dir, args.season, recommendation
            )
    return _emit(args, result)
