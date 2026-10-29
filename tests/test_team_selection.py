"""Other-team forecasts cannot retarget the write binding."""

import json

import pytest

from f1fantasy import account, cli
from test_account import catalog, fixture, history, raw, state, install
from test_v3_cli import game


@pytest.mark.parametrize("team", [1, 2, 3])
def test_explicit_team_read_does_not_rebind(
    tmp_path, monkeypatch, state, catalog, team
):
    session = install(monkeypatch, tmp_path, [state], catalog)
    original = account._read_json(tmp_path / "binding.json")
    observed = []

    def snapshot(session, binding):
        observed.append(binding["team_number"])
        return dict(state, team_number=binding["team_number"]), catalog

    monkeypatch.setattr(account, "_snapshot", snapshot)
    result = account.show(tmp_path, 2026, team_number=team)
    assert result["team_number"] == team and observed == [team]
    assert account._read_json(tmp_path / "binding.json") == original
    assert session.posts == []


def test_recommend_uses_explicit_team_and_identifies_output(game, monkeypatch, capsys):
    _, state, path = game
    reads = []

    def show(directory, season, *, team_number=None):
        reads.append(team_number)
        return dict(
            state, gameday_id=10, team_number=team_number, eligible_chips=["x3"]
        )

    monkeypatch.setattr(account, "show", show)
    assert (
        cli.main(["--season", "2026", "recommend", "--team", "3", "--format", "json"])
        == 0
    )
    assert reads == [3]
    assert json.loads(capsys.readouterr().out)["data"]["team_number"] == 3


def test_team_cannot_be_ignored_in_local_mode(capsys):
    assert (
        cli.main(["recommend", "--team", "2", "--no-account", "--format", "json"]) == 1
    )
    assert "requires an authenticated account" in capsys.readouterr().err
