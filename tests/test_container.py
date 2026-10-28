"""Container auth bootstrap is explicit, persistent and read-only when valid."""

import argparse
import os
from datetime import datetime, timedelta, timezone

import pytest

from f1fantasy import account, container
from f1fantasy.data import DataError


@pytest.fixture
def args(tmp_path, monkeypatch):
    monkeypatch.delenv("F1FANTASY_TEAM", raising=False)
    monkeypatch.delenv("F1FANTASY_RECONNECT", raising=False)
    monkeypatch.delenv("F1FANTASY_HEADLESS", raising=False)
    monkeypatch.setattr(
        account, "connect", lambda *a, **k: pytest.fail("unexpected login")
    )
    return argparse.Namespace(account_dir=tmp_path, season=2026)


def bind(args):
    account._atomic(
        args.account_dir / "binding.json",
        dict(guid="private", season=2026, team_number=2),
    )


def test_first_boot_requires_explicit_team(args):
    with pytest.raises(DataError, match="First start requires"):
        container.bootstrap(args)


@pytest.mark.parametrize("team", ["0", "4", "not-a-team"])
def test_invalid_team_is_never_guessed(args, monkeypatch, team):
    monkeypatch.setenv("F1FANTASY_TEAM", team)
    with pytest.raises(DataError):
        container.bootstrap(args)


def test_existing_valid_session_starts_headless_without_login(args, monkeypatch):
    bind(args)

    def show(*a):
        assert os.environ["F1FANTASY_HEADLESS"] == "1"
        return {"team_number": 2}

    monkeypatch.setattr(account, "show", show)
    container.bootstrap(args)
    assert "F1FANTASY_HEADLESS" not in os.environ


def test_environment_cannot_retarget_saved_account(args, monkeypatch):
    bind(args)
    monkeypatch.setenv("F1FANTASY_TEAM", "1")
    with pytest.raises(DataError, match="differs from the saved team"):
        container.bootstrap(args)


@pytest.mark.parametrize("existing", [False, True])
def test_missing_or_expired_session_connects_in_visible_container_browser(
    args, monkeypatch, existing
):
    monkeypatch.setenv("F1FANTASY_TEAM", "2")
    if existing:
        bind(args)

    def expired(*a):
        raise account.AccountError("expired")

    monkeypatch.setattr(account, "show", expired)

    def connect(directory, season, team, timeout_seconds):
        assert (directory, season, team, timeout_seconds) == (
            args.account_dir,
            2026,
            2,
            900,
        )
        assert os.environ["F1FANTASY_HEADLESS"] == "0"

    monkeypatch.setattr(account, "connect", connect)
    container.bootstrap(args)


def test_forced_reconnect_does_not_silently_skip_login(args, monkeypatch):
    bind(args)
    monkeypatch.setenv("F1FANTASY_RECONNECT", "1")
    calls = []
    monkeypatch.setattr(account, "show", lambda *a: pytest.fail("explicit renewal"))
    monkeypatch.setattr(account, "connect", lambda *a, **k: calls.append(a))
    container.bootstrap(args)
    assert calls[0][-1] == 2


@pytest.mark.parametrize(
    "status,age,expected",
    [
        ("running", 60, 0),
        ("running", 1000, 1),
        ("blocked", 0, 1),
        ("not_started", 0, 1),
    ],
)
def test_health_reports_blocked_or_stale_scheduler(monkeypatch, status, age, expected):
    monkeypatch.setattr(
        container.scheduler,
        "status",
        lambda *a: dict(
            status=status,
            checked_at=(
                datetime.now(timezone.utc) - timedelta(seconds=age)
            ).isoformat(),
        ),
    )
    assert container.health() == expected
