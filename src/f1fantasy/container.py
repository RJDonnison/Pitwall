"""Container bootstrap: one interactive login, then the ordinary durable daemon."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import account, cli, scheduler
from .data import DataError


def _wait_port(port, process):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        if process.poll() is not None:
            raise DataError("Container browser desktop failed to start")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise DataError("Container browser desktop did not become ready")


@contextmanager
def desktop():
    """Own the virtual display and localhost-published interactive login UI."""
    children = []
    try:
        children.append(
            subprocess.Popen(
                [
                    "Xvfb",
                    ":99",
                    "-screen",
                    "0",
                    "1440x900x24",
                    "-nolisten",
                    "tcp",
                    "-ac",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        # x11vnc waits for Xvfb instead of relying on a fixed startup sleep.
        children.append(
            subprocess.Popen(
                [
                    "x11vnc",
                    "-display",
                    ":99",
                    "-rfbport",
                    "5900",
                    "-localhost",
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-quiet",
                    "-noxdamage",
                    "-loop",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        _wait_port(5900, children[-1])
        children.append(
            subprocess.Popen(
                ["websockify", "--web=/usr/share/novnc", "6080", "127.0.0.1:5900"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        _wait_port(6080, children[-1])
        yield
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


@contextmanager
def _browser_mode(headless):
    previous = os.environ.get("F1FANTASY_HEADLESS")
    os.environ["F1FANTASY_HEADLESS"] = "1" if headless else "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("F1FANTASY_HEADLESS", None)
        else:
            os.environ["F1FANTASY_HEADLESS"] = previous


def bootstrap(args):
    """Bind explicitly and renew auth without silently choosing a different team."""
    supplied = os.environ.get("F1FANTASY_TEAM", "")
    requested = account._integer(supplied, "F1FANTASY_TEAM", 1) if supplied else None
    if requested is not None and requested not in (1, 2, 3):
        raise DataError("F1FANTASY_TEAM must be the explicit team number 1, 2 or 3")
    binding_path = args.account_dir / "binding.json"
    if binding_path.exists():
        with account._locked(args.account_dir):
            binding = account._binding(args.account_dir, args.season)
        team = binding["team_number"]
        if requested is not None and requested != team:
            raise DataError(
                "F1FANTASY_TEAM differs from the saved team; use a separate data volume"
            )
        if os.environ.get("F1FANTASY_RECONNECT") != "1":
            try:
                with _browser_mode(True):
                    account.show(args.account_dir, args.season)
                return
            except (DataError, OSError):
                print(
                    "Saved session needs attention; opening official login in the local browser UI.",
                    flush=True,
                )
    elif requested is None:
        raise DataError(
            "First start requires F1FANTASY_TEAM=1, 2 or 3; it is never chosen automatically"
        )
    else:
        team = requested
    print(
        f"Sign in and select Team {team} at http://localhost:6080/vnc.html?autoconnect=1&resize=scale ; complete MFA and open My Team.",
        flush=True,
    )
    timeout = account._integer(
        os.environ.get("F1FANTASY_LOGIN_TIMEOUT", "900"), "login timeout", 1
    )
    with _browser_mode(False):
        account.connect(args.account_dir, args.season, team, timeout_seconds=timeout)
    print(f"Team {team} connected; starting automatic scheduling.", flush=True)


def health():
    healthy = "running"
    if os.environ.get("F1FANTASY_SERVICE") == "predict":
        from . import predict_scheduler

        state = predict_scheduler.status(cli.DEFAULT_ACCOUNT)
        healthy = "active"
    else:
        state = scheduler.status(cli.DEFAULT_ACCOUNT)
    if state.get("status") != healthy or not state.get("checked_at"):
        return 1
    age = (
        datetime.now(timezone.utc) - scheduler.timestamp(state["checked_at"])
    ).total_seconds()
    return 0 if 0 <= age < 900 else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv) or [
        "daemon",
        "run",
        "--season-plan",
        "--allow-penalties",
    ]
    try:
        if argv == ["health"]:
            return health()
        args = cli._parser().parse_args(argv)
        predict_daemon = (
            args.command == "predict"
            and args.predict_action == "daemon"
            and args.predict_daemon_action == "run"
        )
        if not predict_daemon and (
            args.command != "daemon" or args.daemon_action != "run"
        ):
            return cli.main(argv)
        with desktop():
            if predict_daemon:
                bootstrap_predict(args)
            else:
                bootstrap(args)
            return cli.main(argv)
    except DataError as exc:
        print(f"Container setup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    except OSError:
        # Account errors are already sanitized. Do not expose child-process or
        # browser exception details that could contain session material.
        print(
            "Container setup failed; check the team selection, persistent volume ownership and login. Use account/daemon status for details.",
            file=sys.stderr,
            flush=True,
        )
        return 1


def bootstrap_predict(args):
    """Predict has its own account/profile and cannot reuse a Fantasy binding."""
    from . import predict_account

    saved = predict_account.storage_directory(args.account_dir) / "binding.json"
    if saved.exists() and os.environ.get("F1FANTASY_RECONNECT") != "1":
        try:
            with _browser_mode(True):
                predict_account.show(args.account_dir, args.season, scope=args.scope)
            return
        except (DataError, OSError):
            print(
                "Predict session needs attention; opening official login.", flush=True
            )
    print(
        "Sign into F1 Predict at http://localhost:6081/vnc.html?autoconnect=1&resize=scale ; complete MFA and open your predictions. Fantasy login remains separate.",
        flush=True,
    )
    timeout = account._integer(
        os.environ.get("F1FANTASY_LOGIN_TIMEOUT", "900"), "login timeout", 1
    )
    with _browser_mode(False):
        predict_account.connect(args.account_dir, args.season, timeout_seconds=timeout)


if __name__ == "__main__":
    raise SystemExit(main())
