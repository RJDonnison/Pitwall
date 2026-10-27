import json
from datetime import datetime, timezone

from f1fantasy import cli
from f1fantasy.data import Asset, Snapshot, Weekend
from f1fantasy.projections import Estimate


def test_cli_import_and_recommendation(tmp_path, monkeypatch, capsys):
    assets = tuple(
        [
            Asset(str(i), f"Driver {i}", "DRIVER", str(i // 2), 50, f"D{i}")
            for i in range(20)
        ]
        + [Asset(f"c{i}", f"Team {i}", "CONSTRUCTOR", str(i), 50) for i in range(10)]
    )
    weekend = Weekend(
        2026, 4, "Miami", 4, datetime(2026, 5, 2, tzinfo=timezone.utc), True, False
    )
    live = Snapshot(
        weekend, assets, datetime.now(timezone.utc), datetime.now(timezone.utc)
    )
    monkeypatch.setattr(cli, "snapshot", lambda _, **_kwargs: (live, [weekend]))
    monkeypatch.setattr(
        cli,
        "estimate_assets",
        lambda a, w, **kwargs: {(0, item.id): Estimate(2, 3, 5) for item in a},
    )
    state_file = tmp_path / "team.json"
    import_file = tmp_path / "import.json"
    import_file.write_text(
        json.dumps(
            {
                "season": 2026,
                "drivers": [0, 1, 2, 3, 4],
                "constructors": ["c0", "c1"],
                "budget": 100.0,
                "carry": 1,
            }
        )
    )
    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--state",
                str(state_file),
                "init",
                "--import-file",
                str(import_file),
            ]
        )
        == 0
    )
    assert state_file.exists()
    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--state",
                str(state_file),
                "recommend",
                "--no-account",
                "--no-chips",
                "--races",
                "1",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "2x Boost" in printed
    assert "Sprint 24.0" in printed
    assert "Net transfers" in printed
    assert "Projected 1-race total" in printed
    last_week = Weekend(
        2026, 3, "Japan", 3, datetime(2026, 4, 1, tzinfo=timezone.utc), False, True
    )
    preview = Snapshot(weekend, assets, live.fetched_at, live.published_at, last_week)
    seen = []

    def provisional_snapshot(_, *, allow_old_prices=False):
        seen.append(allow_old_prices)
        return preview, [weekend]

    monkeypatch.setattr(cli, "snapshot", provisional_snapshot)
    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--state",
                str(state_file),
                "recommend",
                "--no-account",
                "--no-chips",
                "--races",
                "1",
                "--allow-old-prices",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert seen == [True]
    assert "PROVISIONAL" in printed and "Re-run without --allow-old-prices" in printed


def test_rejects_unverified_import(tmp_path, monkeypatch, capsys):
    weekend = Weekend(
        2026, 4, "Miami", 4, datetime(2026, 5, 2, tzinfo=timezone.utc), True, False
    )
    live = Snapshot(weekend, (), datetime.now(timezone.utc), datetime.now(timezone.utc))
    monkeypatch.setattr(cli, "snapshot", lambda _, **_kwargs: (live, [weekend]))
    state = tmp_path / "team.json"
    assert (
        cli.main(
            [
                "--season",
                "2026",
                "--state",
                str(state),
                "init",
                "--drivers",
                "1",
                "2",
                "3",
                "4",
                "5",
                "--constructors",
                "c1",
                "c2",
                "--budget",
                "100",
            ]
        )
        == 1
    )
    assert "missing or inactive" in capsys.readouterr().err
    assert not state.exists()
