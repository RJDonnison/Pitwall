from datetime import datetime, timezone

from f1fantasy.data import Asset, Weekend
from f1fantasy.optimizer import optimize
from f1fantasy.projections import Estimate


def fixture(sprint=False):
    assets = tuple(
        [
            Asset(str(i), f"Driver {i}", "DRIVER", str(i // 2), 50, f"D{i}")
            for i in range(8)
        ]
        + [Asset(f"c{i}", f"Team {i}", "CONSTRUCTOR", str(i), 50) for i in range(4)]
    )
    weekends = [
        Weekend(
            2026,
            i + 1,
            f"Round {i}",
            i + 1,
            datetime(2026, 11, i + 1, tzinfo=timezone.utc),
            sprint if i == 0 else False,
            False,
        )
        for i in range(2)
    ]
    scores = {(t, a.id): Estimate(1, 0, 1) for t in range(2) for a in assets}
    return assets, weekends, scores


def test_sprint_points_choose_different_boost():
    assets, weekends, scores = fixture(sprint=True)
    scores[0, "7"] = Estimate(1, 20, 1)
    scores[0, "6"] = Estimate(1, 0, 9)
    result = optimize(assets, weekends[:1], scores, 350)
    assert len(result[0].drivers) == 5 and len(result[0].constructors) == 2
    assert result[0].cost == 350
    assert result[0].boost.id == "7"


def test_net_transfers_and_carry_over():
    assets, weekends, scores = fixture()
    previous = frozenset(["0", "1", "2", "3", "4", "c0", "c1"])
    for id_ in ("5", "6", "7", "c2"):
        scores[0, id_] = Estimate(5, 0, 20)
        scores[1, id_] = Estimate(5, 0, 20)
    result = optimize(assets, weekends, scores, 350, previous=previous)
    assert result[0].transfers <= 2
    assert result[1].transfers <= 3
    assert result[0].transfers + result[1].transfers <= 4
    assert all(r.transfer_penalty == 0 for r in result)


def test_extra_transfers_pay_penalty():
    assets, weekends, scores = fixture()
    previous = frozenset(["0", "1", "2", "3", "4", "c0", "c1"])
    for id_ in ("5", "6", "7", "c2"):
        scores[0, id_] = Estimate(0, 0, 80)
    result = optimize(
        assets, weekends[:1], scores, 350, previous=previous, allow_penalties=True
    )
    assert result[0].transfers > 2
    assert result[0].transfer_penalty == 10 * (result[0].transfers - 2)
