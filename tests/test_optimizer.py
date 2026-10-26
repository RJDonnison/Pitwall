from datetime import datetime, timezone
from itertools import combinations, product

import pytest

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


@pytest.mark.parametrize(
    "previous,carry,penalties",
    [
        (None, 0, False),
        (frozenset(["0", "1", "2", "3", "4", "c0", "c1"]), 0, False),
        (frozenset(["0", "1", "2", "3", "4", "c0", "c1"]), 1, True),
    ],
)
def test_two_race_total_matches_exhaustive_search(previous, carry, penalties):
    drivers = [
        Asset(str(i), f"D{i}", "DRIVER", str(i // 2), i + 3, f"D{i}") for i in range(6)
    ]
    constructors = [
        Asset(f"c{i}", f"C{i}", "CONSTRUCTOR", str(i), 15 + i * 2) for i in range(3)
    ]
    assets = tuple(drivers + constructors)
    weekends = [
        Weekend(
            2026,
            t + 1,
            f"Race {t}",
            t + 1,
            datetime(2026, 11, t + 1, tzinfo=timezone.utc),
            False,
            False,
        )
        for t in range(2)
    ]
    points = [[20, 18, 12, 11, 5, 0, 14, 8, 4], [2, 6, 12, 14, 25, 28, 4, 7, 20]]
    scores = {
        (t, a.id): Estimate(0, 0, points[t][i])
        for t in range(2)
        for i, a in enumerate(assets)
    }
    budget = 60
    lineups = [
        tuple(d + c)
        for d, c in product(combinations(drivers, 5), combinations(constructors, 2))
        if sum(a.price for a in d + c) <= budget
    ]

    def value(t, lineup):
        return sum(scores[t, a.id].total for a in lineup) + max(
            scores[t, a.id].total for a in lineup if a.kind == "DRIVER"
        )

    def transfers(lineup, old):
        return len({a.id for a in lineup} - old)

    best = float("-inf")
    for first, second in product(lineups, repeat=2):
        incoming = transfers(first, previous) if previous is not None else 0
        free = 2 + carry
        extra = max(0, incoming - free) if previous is not None else 0
        if extra and not penalties:
            continue
        next_carry = int(previous is not None and extra == 0 and incoming < free)
        second_incoming = transfers(second, {a.id for a in first})
        second_extra = max(0, second_incoming - 2 - next_carry)
        if second_extra and not penalties:
            continue
        best = max(
            best, value(0, first) + value(1, second) - 10 * (extra + second_extra)
        )

    result = optimize(
        assets,
        weekends,
        scores,
        budget,
        previous=previous,
        carry=carry,
        allow_penalties=penalties,
    )
    assert sum(row.expected_points for row in result) == pytest.approx(best)
