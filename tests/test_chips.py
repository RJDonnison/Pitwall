from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import combinations, product

import pytest

from f1fantasy import chips, data
from f1fantasy.chips import ChipValues, final_fix, load_chip_values
from f1fantasy.data import Asset, DataError, Weekend
from f1fantasy.optimizer import optimize
from f1fantasy.projections import Estimate


def fixture(rounds=2):
    assets = tuple(
        [Asset(str(i), f"D{i}", "DRIVER", str(i // 2), 3 + i) for i in range(6)]
        + [Asset(f"c{i}", f"C{i}", "CONSTRUCTOR", str(i), 15 + 2 * i) for i in range(3)]
    )
    weekends = [
        Weekend(
            2026,
            t + 2,
            f"Race {t}",
            t + 2,
            datetime(2026, 11, t + 1, tzinfo=timezone.utc),
            False,
            False,
        )
        for t in range(rounds)
    ]
    points = [[20, 18, 12, 11, 5, 0, 14, 8, 4], [2, 6, 12, 14, 25, 28, 4, 7, 20]]
    estimates = {
        (t, a.id): Estimate(0, 0, points[t % 2][i])
        for t in range(rounds)
        for i, a in enumerate(assets)
    }
    previous = frozenset(["0", "1", "2", "3", "4", "c0", "c1"])
    return assets, weekends, estimates, previous


def ids(lineup):
    return frozenset(a.id for a in lineup.drivers + lineup.constructors)


def test_x3_is_distinct_from_regular_boost():
    assets, weekends, estimates, _ = fixture(1)
    lineup = optimize(
        assets,
        weekends,
        estimates,
        100,
        available_chips=frozenset({"x3"}),
        forced_chip="x3",
    )[0]
    assert lineup.x3.id == "0"
    assert lineup.boost.id == "1"
    assert lineup.x3 != lineup.boost
    assert lineup.x3 in lineup.drivers
    assert lineup.expected_points == pytest.approx(
        sum(estimates[0, a].total for a in ids(lineup)) + 2 * 20 + 18
    )
    assert lineup.session_points.total == lineup.expected_points


@pytest.mark.parametrize("chip", ["autopilot", "no_negative", "x3", "wildcard"])
def test_active_chip_keeps_scoring_without_inventory_or_spending_reserve(chip):
    assets, weekends, estimates, previous = fixture(2)
    values = ChipValues(
        no_negative={key: Estimate(0, 0, 2) for key in estimates},
        autopilot={
            t: ({a.id: estimates[t, a.id] for a in assets if a.kind == "DRIVER"},)
            for t in range(2)
        },
    )
    result = optimize(
        assets,
        weekends,
        estimates,
        100,
        previous,
        active_chip=chip,
        chip_values=values,
        chip_reserve={chip: 1e6},
        eligible_chips={},
    )
    assert result[0].chip == chip
    assert result[1].chip is None
    forced = optimize(
        assets,
        weekends,
        estimates,
        100,
        previous,
        available_chips=frozenset({chip}),
        forced_chip=chip,
        chip_values=values,
    )
    assert sum(p.expected_points for p in result) == pytest.approx(
        sum(p.expected_points for p in forced)
    )


def test_active_chip_cannot_be_replaced_by_forced_other_chip():
    assets, weekends, estimates, previous = fixture(1)
    with pytest.raises(DataError, match="cannot be cancelled"):
        optimize(
            assets,
            weekends,
            estimates,
            100,
            previous,
            active_chip="x3",
            forced_chip="wildcard",
        )


def test_active_limitless_without_restoration_is_single_weekend_and_uncapped():
    assets, weekends, estimates, previous = fixture(1)
    result = optimize(
        assets,
        weekends,
        estimates,
        1,
        previous,
        active_chip="limitless",
    )[0]
    assert result.chip == "limitless"
    assert len(ids(result)) == 7
    assert result.cost > 1
    assert result.transfer_penalty == 0
    with pytest.raises(DataError, match="single-weekend"):
        optimize(
            assets,
            weekends * 2,
            estimates,
            1,
            previous,
            active_chip="limitless",
        )


def test_nn_applies_per_asset_and_to_boost_without_clamping_forecast():
    assets, weekends, estimates, _ = fixture(1)
    estimates = {key: Estimate(5, 0, 3) for key in estimates}
    # Positive net sessions can still have negative scoring categories removed.
    uplift = {
        (0, a.id): Estimate(1, 0, 7 if a.kind == "CONSTRUCTOR" else 2) for a in assets
    }
    lineup = optimize(
        assets,
        weekends,
        estimates,
        100,
        available_chips=frozenset({"no_negative"}),
        chip_values=ChipValues(no_negative=uplift),
        forced_chip="no_negative",
    )[0]
    # Eight base copies, six driver uplift copies, two constructor copies.
    assert lineup.session_points == Estimate(8 * 6, 0, 8 * 3 + 6 * 2 + 2 * 7)
    assert lineup.expected_points == lineup.session_points.total


def test_autopilot_maximum_total_weekend_not_per_session_or_fixed_boost():
    assets, weekends, estimates, _ = fixture(1)
    estimates = {key: Estimate(0, 0, 0) for key in estimates}
    scenarios = []
    for sign in (1, -1):
        s = {a.id: Estimate(0, 0, 0) for a in assets if a.kind == "DRIVER"}
        s["0"] = Estimate(sign * 40, 0, -sign * 30)  # total +/-10
        s["1"] = Estimate(-sign * 20, 0, 0)  # total -/+20
        scenarios.append(s)
    lineup = optimize(
        assets,
        weekends,
        estimates,
        100,
        available_chips=frozenset({"autopilot"}),
        chip_values=ChipValues(autopilot={0: tuple(scenarios)}),
        forced_chip="autopilot",
    )[0]
    assert {"0", "1"} <= ids(lineup)
    assert lineup.expected_points == 15
    assert lineup.session_points == Estimate(30, 0, -15)


@pytest.mark.parametrize(
    "chip", ["x3", "no_negative", "autopilot", "wildcard", "limitless", "all"]
)
@pytest.mark.parametrize("penalties", [False, True])
def test_two_round_chip_and_net_transfers_match_exhaustive_search(chip, penalties):
    assets, weekends, estimates, previous = fixture()
    budget = 60
    all_teams = [
        d + c
        for d, c in product(combinations(assets[:6], 5), combinations(assets[6:], 2))
    ]
    capped = [team for team in all_teams if sum(a.price for a in team) <= budget]
    nn = {
        (t, a.id): Estimate(0, 0, 2 + i % 3)
        for t in range(2)
        for i, a in enumerate(assets)
    }
    ap = {
        t: tuple(
            {
                a.id: Estimate(0, 0, estimates[t, a.id].total + sign * (i - 2) * 5)
                for i, a in enumerate(assets[:6])
            }
            for sign in (-1, 1)
        )
        for t in range(2)
    }
    values = ChipValues(nn, ap)
    reserve = 3.5

    def value(t, team, active):
        ds = [a for a in team if a.kind == "DRIVER"]
        scores = {a.id: estimates[t, a.id].total for a in team}
        if active == "no_negative":
            scores = {a.id: scores[a.id] + nn[t, a.id].total for a in team}
        base = sum(scores.values())
        if active == "autopilot":
            return base + sum(max(s[a.id].total for a in ds) for s in ap[t]) / len(
                ap[t]
            )
        if active == "x3":
            return base + max(
                2 * scores[a.id] + scores[b.id] for a in ds for b in ds if a != b
            )
        return base + max(scores[a.id] for a in ds)

    best = float("-inf")
    inventory = (
        frozenset({"x3", "no_negative", "autopilot", "wildcard", "limitless"})
        if chip == "all"
        else frozenset({chip})
    )
    for schedule in product([None, *sorted(inventory)], repeat=2):
        if schedule[0] is not None and schedule[0] == schedule[1]:
            continue
        choices = [
            all_teams if schedule[t] == "limitless" else capped for t in range(2)
        ]
        for teams in product(*choices):
            old, carry, total = previous, 1, 0
            for t, team in enumerate(teams):
                active = schedule[t]
                selected = frozenset(a.id for a in team)
                count = len(selected - old)
                extra = (
                    0
                    if active in {"wildcard", "limitless"}
                    else max(0, count - 2 - carry)
                )
                if extra and not penalties:
                    break
                total += value(t, team, active) - 10 * extra
                if active:
                    total -= reserve
                carry = int(active != "limitless" and count < 2 + carry and not extra)
                if active != "limitless":
                    old = selected
            else:
                best = max(best, total)
    output = optimize(
        assets,
        weekends,
        estimates,
        budget,
        previous,
        carry=1,
        allow_penalties=penalties,
        available_chips=inventory,
        chip_values=values,
        chip_reserve={name: reserve for name in inventory},
    )
    actual = sum(
        lineup.expected_points - (reserve if lineup.chip else 0) for lineup in output
    )
    assert actual == pytest.approx(best)


def test_limitless_restores_baseline_and_resets_bank():
    assets, weekends, estimates, previous = fixture()
    for a in assets:
        estimates[0, a.id] = Estimate(0, 0, a.price)
    # All six drivers + three constructors cost enough that the LL team differs.
    output = optimize(
        assets,
        weekends,
        estimates,
        60,
        previous,
        carry=1,
        available_chips=frozenset({"limitless"}),
        forced_chip="limitless",
    )
    assert output[0].cost > 60
    assert output[0].transfer_penalty == 0
    assert output[1].transfers == len(ids(output[1]) - previous)
    assert output[1].transfers <= 2


def test_limitless_baseline_survives_multiple_rounds():
    assets, weekends, estimates, previous = fixture(3)
    for a in assets:
        estimates[1, a.id] = Estimate(0, 0, a.price * 10)
    output = optimize(
        assets,
        weekends,
        estimates,
        60,
        previous,
        available_chips=frozenset({"limitless", "wildcard"}),
        eligible_chips={1: frozenset({"limitless"})},
    )
    assert output[1].chip == "limitless"
    assert output[2].transfers == len(ids(output[2]) - ids(output[0]))
    assert output[2].transfers <= 2


def transfer_fixture():
    assets = tuple(
        [Asset(str(i), f"D{i}", "DRIVER", str(i // 2), 10) for i in range(8)]
        + [Asset(f"c{i}", f"C{i}", "CONSTRUCTOR", str(i), 10) for i in range(4)]
    )
    _, weekends, _, previous = fixture()
    scores = {
        (t, a.id): Estimate(0, 0, 100 if (a.id in previous) == (t == 0) else 0)
        for t in range(2)
        for a in assets
    }
    return assets, weekends, scores, previous


@pytest.mark.parametrize("chip", ["wildcard", "limitless"])
@pytest.mark.parametrize("carry", [0, 1])
def test_unlimited_transfers_match_exhaustive_search(chip, carry):
    assets, weekends, scores, previous = transfer_fixture()
    assets = tuple(replace(a, price=20 if a.id not in previous else 10) for a in assets)
    # Five desirable newcomers exceed both the ordinary free allowance and cap.
    scores = {
        (0, a.id): Estimate(0, 0, 100 if a.id not in previous else 0) for a in assets
    }
    budget = 100
    candidates = [
        d + c
        for d, c in product(combinations(assets[:8], 5), combinations(assets[8:], 2))
        if chip == "limitless" or sum(a.price for a in d + c) <= budget
    ]
    best = max(
        sum(scores[0, a.id].total for a in team)
        + max(scores[0, a.id].total for a in team if a.kind == "DRIVER")
        for team in candidates
    )
    result = optimize(
        assets,
        weekends[:1],
        scores,
        budget,
        previous,
        carry=carry,
        available_chips=frozenset({chip}),
        forced_chip=chip,
    )[0]
    assert result.expected_points == best
    assert result.transfers > 2
    assert result.transfers == len(ids(result) - previous)
    assert result.transfer_penalty == 0
    assert result.cost <= budget if chip == "wildcard" else result.cost > budget


def test_limitless_clears_carried_transfer_even_when_no_transfer_is_used():
    assets, weekends, scores, previous = transfer_fixture()
    first, second = optimize(
        assets,
        weekends,
        scores,
        70,
        previous,
        carry=1,
        allow_penalties=True,
        available_chips=frozenset({"limitless"}),
        forced_chip="limitless",
    )
    assert ids(first) == previous
    assert first.transfers == 0
    assert second.transfers == 5
    assert second.transfer_penalty == 30


def test_sprint_forecast_and_nn_uplift_both_receive_boost():
    assets, weekends, estimates, _ = fixture(1)
    weekends[0] = replace(weekends[0], sprint=True)
    estimates = {key: Estimate(0, 1, 0) for key in estimates}
    nn = {(0, a.id): Estimate(0, 3 if a.id == "5" else 0, 0) for a in assets}
    result = optimize(
        assets,
        weekends,
        estimates,
        100,
        available_chips=frozenset({"no_negative"}),
        chip_values=ChipValues(no_negative=nn),
        forced_chip="no_negative",
    )[0]
    assert result.boost.id == "5"
    assert result.session_points == Estimate(0, 14, 0)


def test_reserve_saves_chip_beyond_horizon_and_is_not_reported_as_score():
    assets, weekends, estimates, _ = fixture(1)
    kwargs = dict(available_chips=frozenset({"x3"}), chip_reserve={"x3": 1000})
    saved = optimize(assets, weekends, estimates, 100, **kwargs)[0]
    assert saved.chip is None
    forced = optimize(assets, weekends, estimates, 100, forced_chip="x3", **kwargs)[0]
    assert forced.chip == "x3"
    assert forced.expected_points == forced.session_points.total


def test_chip_inventory_once_per_season_one_per_weekend_and_eligibility():
    assets, weekends, estimates, _ = fixture(3)
    output = optimize(
        assets,
        weekends,
        estimates,
        100,
        available_chips=frozenset({"x3", "wildcard", "final_fix"}),
        eligible_chips={1: frozenset({"x3"}), 2: frozenset({"x3"})},
    )
    assert output[0].chip is None
    assert sum(row.chip == "x3" for row in output) == 1
    assert all(row.chip in {None, "x3"} for row in output)
    assert all(row.chip is None for row in optimize(assets, weekends, estimates, 100))
    for forced in ("final_fix", "autopilot", "unknown"):
        with pytest.raises(DataError):
            optimize(
                assets,
                weekends,
                estimates,
                100,
                available_chips=frozenset({"final_fix", "x3"}),
                forced_chip=forced,
            )
    with pytest.raises(DataError):
        optimize(
            assets,
            weekends,
            estimates,
            100,
            available_chips=frozenset({"x3"}),
            eligible_chips={0: frozenset()},
            forced_chip="x3",
        )


def test_first_round_allows_immediate_chips_but_not_unlocked_chips():
    assets, weekends, estimates, previous = fixture(1)
    first = [replace(weekends[0], round=1)]
    assert (
        optimize(
            assets,
            first,
            estimates,
            100,
            available_chips=frozenset({"x3"}),
            forced_chip="x3",
        )[0].chip
        == "x3"
    )
    for name in ("wildcard", "limitless"):
        with pytest.raises(DataError):
            optimize(
                assets,
                first,
                estimates,
                100,
                previous,
                available_chips=frozenset({name}),
                forced_chip=name,
            )


@pytest.mark.parametrize("chip", ["autopilot", "no_negative"])
def test_missing_empirical_inputs_fail_closed_only_when_eligible(chip):
    assets, weekends, estimates, _ = fixture(1)
    with pytest.raises(DataError):
        optimize(assets, weekends, estimates, 100, available_chips=frozenset({chip}))
    assert (
        optimize(
            assets,
            weekends,
            estimates,
            100,
            available_chips=frozenset({chip}),
            eligible_chips={},
        )[0].chip
        is None
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_values(value):
    assets, weekends, estimates, _ = fixture(1)
    with pytest.raises(DataError):
        optimize(assets, weekends, estimates, 100, chip_reserve={"x3": value})
    nn = {(0, a.id): Estimate(value, 0, 0) for a in assets}
    with pytest.raises(DataError):
        optimize(
            assets,
            weekends,
            estimates,
            100,
            available_chips=frozenset({"no_negative"}),
            chip_values=ChipValues(no_negative=nn),
        )


def test_autopilot_rejects_uncentered_or_incomplete_scenarios():
    assets, weekends, estimates, _ = fixture(1)
    for scenario in ({}, {a.id: Estimate(0, 0, 999) for a in assets[:6]}):
        with pytest.raises(DataError):
            optimize(
                assets,
                weekends,
                estimates,
                100,
                available_chips=frozenset({"autopilot"}),
                chip_values=ChipValues(autopilot={0: (scenario,)}),
            )


def historical_feed(assets, n, sprint=False):
    return {
        "Value": [
            {
                "PlayerId": a.id,
                "PositionName": a.kind,
                "GamedayPoints": 10 + n + (4 if sprint else 0),
                "SessionWisePoints": [
                    {"sessiontype": "Qualifying", "points": 2, "nonegative_points": 3},
                    *(
                        [
                            {
                                "sessiontype": "Sprint",
                                "points": 4,
                                "nonegative_points": 11,
                            }
                        ]
                        if sprint
                        else []
                    ),
                    {
                        "sessiontype": "Race",
                        "points": 8 + n,
                        "nonegative_points": 13
                        + n
                        + (6 if a.kind == "CONSTRUCTOR" else 0),
                    },
                ],
            }
            for a in assets
        ]
    }


def history_fixture(monkeypatch):
    assets, weekends, estimates, _ = fixture()
    weekends[1] = replace(weekends[1], sprint=True)
    cutoff = weekends[0].first_session

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cutoff - timedelta(days=1)

    monkeypatch.setattr(chips, "datetime", Clock)
    history = [
        replace(
            weekends[0],
            gameday_id=i,
            sprint=(i % 2 == 0),
            first_session=cutoff - timedelta(days=30 - i),
            last_session=cutoff - timedelta(days=29 - i),
        )
        for i in range(1, 15)
    ]
    # These must never be fetched, including later-horizon completed weekends.
    history += [
        replace(weekends[0], gameday_id=90, last_session=cutoff),
        replace(weekends[0], gameday_id=91, last_session=cutoff + timedelta(hours=1)),
        replace(history[0], gameday_id=92, season=2025),
        replace(history[0], gameday_id=93, last_session=None),
        replace(
            weekends[0],
            gameday_id=94,
            first_session=cutoff - timedelta(days=2),
            last_session=cutoff - timedelta(hours=12),
        ),
    ]
    monkeypatch.setattr(data, "season_weekends", lambda season: history)
    fetched = []

    def get(path):
        n = int(path.split("/")[1].split("_")[0])
        fetched.append(n)
        return historical_feed(assets, n, sprint=(n % 2 == 0))

    monkeypatch.setattr(data, "_get_json", get)
    return assets, weekends, estimates, fetched, get


def test_loader_strict_cutoff_last_five_same_type_and_official_category_uplift(
    monkeypatch,
):
    assets, weekends, estimates, fetched, _ = history_fixture(monkeypatch)
    values = load_chip_values(assets, weekends, estimates)
    assert set(fetched) == {5, 7, 9, 11, 13, 6, 8, 10, 12, 14}
    assert len(fetched) == 10
    assert values.no_negative[0, "0"] == Estimate(1, 0, 5)
    assert values.no_negative[0, "c0"] == Estimate(1, 0, 11)
    assert values.no_negative[1, "c0"] == Estimate(1, 7, 11)
    for t in range(2):
        assert len(values.autopilot[t]) == 5
        for a in assets[:6]:
            for k in range(3):
                mean = (
                    sum(chips.components(s[a.id])[k] for s in values.autopilot[t]) / 5
                )
                assert mean == pytest.approx(chips.components(estimates[t, a.id])[k])
        # Correlated variation from the same historical weekend is retained.
        deviations = [
            [s[a.id].total - estimates[t, a.id].total for a in assets[:6]]
            for s in values.autopilot[t]
        ]
        assert all(len(set(row)) == 1 for row in deviations)
        assert deviations[0][0] != deviations[-1][0]


def test_no_negative_loader_covers_target_downside_and_scheduler_prefers_it(
    monkeypatch,
):
    assets, weekends, estimates, _, _ = history_fixture(monkeypatch)
    weekends[1] = replace(weekends[1], sprint=False)
    for a in assets:
        estimates[0, a.id] = Estimate(2, 0, 20)
        estimates[1, a.id] = Estimate(-4, 0, -30)
    values = load_chip_values(assets, weekends, estimates)
    assert values.no_negative[0, "0"] == Estimate(1, 0, 5)
    assert values.no_negative[1, "0"] == Estimate(4, 0, 30)
    assert values.no_negative[1, "c0"] == Estimate(4, 0, 30)
    lineups = optimize(
        assets,
        weekends,
        estimates,
        100,
        available_chips=frozenset({"no_negative"}),
        chip_values=values,
    )
    assert lineups[0].chip is None
    assert lineups[1].chip == "no_negative"
    assert lineups[1].session_points == Estimate(0, 0, 0)


def test_no_negative_downside_is_sessionwise_not_net_weekend(monkeypatch):
    assets, weekends, estimates, _, _ = history_fixture(monkeypatch)
    estimates[1, "0"] = Estimate(25, -18, -30)
    values = load_chip_values(assets, weekends, estimates)
    assert values.no_negative[1, "0"] == Estimate(1, 18, 30)


def test_loader_excludes_null_weekends_from_the_entire_joint_sample(monkeypatch):
    assets, weekends, estimates, _, get = history_fixture(monkeypatch)

    def with_gap(path):
        feed = get(path)
        if path == "drivers/5_en.json":
            feed["Value"][0]["SessionWisePoints"][0]["points"] = None
        return feed

    monkeypatch.setattr(data, "_get_json", with_gap)
    values = load_chip_values(assets, weekends, estimates)
    assert values.history_gamedays[0] == (7, 9, 11, 13)
    assert values.skipped_history_gamedays == (5,)
    assert len(values.autopilot[0]) == 4
    assert len(values.autopilot[1]) == 5
    assert values.no_negative[0, "c0"] == Estimate(1, 0, 11)
    for a in assets[:6]:
        assert sum(s[a.id].total for s in values.autopilot[0]) / 4 == pytest.approx(
            estimates[0, a.id].total
        )


def test_loader_fails_when_every_common_sample_has_null_points(monkeypatch):
    assets, weekends, estimates, _, get = history_fixture(monkeypatch)

    def unavailable(path):
        feed = get(path)
        feed["Value"][0]["SessionWisePoints"][0]["nonegative_points"] = None
        return feed

    monkeypatch.setattr(data, "_get_json", unavailable)
    with pytest.raises(DataError, match="No complete common"):
        load_chip_values(assets, weekends, estimates)


@pytest.mark.parametrize(
    "bad", ["missing_asset", "missing_session", "nan", "negative_uplift", "total"]
)
def test_loader_rejects_incomplete_common_samples(monkeypatch, bad):
    assets, weekends, estimates, _, get = history_fixture(monkeypatch)

    def broken(path):
        feed = get(path)
        row = feed["Value"][0]
        if bad == "missing_asset":
            feed["Value"].pop()
        elif bad == "missing_session":
            row["SessionWisePoints"].pop()
        elif bad == "nan":
            row["SessionWisePoints"][0]["nonegative_points"] = float("nan")
        elif bad == "negative_uplift":
            row["SessionWisePoints"][0]["nonegative_points"] = -1
        else:
            row["GamedayPoints"] = 999
        return feed

    monkeypatch.setattr(data, "_get_json", broken)
    with pytest.raises(DataError):
        load_chip_values(assets, weekends, estimates)


def test_loader_requires_matching_completed_history(monkeypatch):
    assets, weekends, estimates, _, _ = history_fixture(monkeypatch)
    monkeypatch.setattr(data, "season_weekends", lambda season: [])
    with pytest.raises(DataError):
        load_chip_values(assets, weekends, estimates)


def test_final_fix_future_only_preserves_accrued_and_inherits_boost():
    assets, weekends, estimates, _ = fixture(1)
    original = optimize(assets, weekends, estimates, 100)[0]
    unselected = next(a for a in assets[:6] if a.id not in ids(original))
    remaining = {a.id: Estimate(0, 0, 0) for a in assets}
    remaining[unselected.id] = Estimate(0, 3, 20)
    result = final_fix(
        original,
        assets,
        remaining,
        100,
        available=True,
        eligible=True,
        accrued_points=123,
    )
    assert result.original is original
    assert result.outgoing == original.boost
    assert result.incoming == unselected
    assert result.boost == unselected
    assert result.remaining_points == Estimate(0, 6, 40)
    assert result.expected_points == 169
    assert result.accrued_points == 123
    assert original.boost.id == "0"
    assert ids(original) != frozenset(
        a.id for a in result.drivers + result.constructors
    )


def test_final_fix_budget_same_kind_and_zero_change():
    assets, weekends, estimates, _ = fixture(1)
    original = optimize(assets, weekends, estimates, 60)[0]
    remaining = {a.id: Estimate(0, 0, 0) for a in assets}
    new_constructor = next(a for a in assets[6:] if a.id not in ids(original))
    remaining[new_constructor.id] = Estimate(0, 0, 100)
    # At a generous budget the single replacement must remain constructor-for-constructor.
    result = final_fix(
        original,
        assets,
        remaining,
        100,
        available=True,
        eligible=True,
        accrued_points=-5,
    )
    assert result.outgoing.kind == result.incoming.kind == "CONSTRUCTOR"
    assert result.boost == original.boost
    # All prices frozen at original budget: enumerate every legal future-only swap.
    result = final_fix(
        original, assets, remaining, 60, available=True, eligible=True, accrued_points=0
    )
    assert result.cost <= 60
    teams = [original.drivers + original.constructors]
    for old in teams[0]:
        for new in assets:
            if new.kind == old.kind and new.id not in ids(original):
                teams.append(tuple(new if a == old else a for a in teams[0]))
    best = max(
        sum(remaining[a.id].total for a in team)
        for team in teams
        if sum(a.price for a in team) <= 60
    )
    assert result.remaining_points.total == best
    zero = final_fix(
        original,
        assets,
        {a.id: Estimate(0, 0, 0) for a in assets},
        100,
        available=True,
        eligible=True,
        accrued_points=0,
    )
    assert zero.incoming is zero.outgoing is None


def test_final_fix_requires_explicit_window_inventory_and_all_remaining_estimates():
    assets, weekends, estimates, _ = fixture(1)
    original = optimize(assets, weekends, estimates, 100)[0]
    remaining = {a.id: Estimate(0, 0, 1) for a in assets}
    for available, eligible in ((False, True), (True, False)):
        with pytest.raises(DataError):
            final_fix(
                original,
                assets,
                remaining,
                100,
                available=available,
                eligible=eligible,
                accrued_points=0,
            )
    for bad in ({}, {**remaining, "0": Estimate(float("nan"), 0, 0)}):
        with pytest.raises(DataError):
            final_fix(
                original,
                assets,
                bad,
                100,
                available=True,
                eligible=True,
                accrued_points=0,
            )
    with pytest.raises(DataError):
        final_fix(
            replace(original, chip="wildcard"),
            assets,
            remaining,
            100,
            available=True,
            eligible=True,
            accrued_points=0,
        )
