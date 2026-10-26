from f1fantasy.data import Asset
from f1fantasy.risk import expected_session_points, reliability_components


def drivers():
    return [
        Asset("a", "A", "DRIVER", "team", 50, "AAA"),
        Asset("b", "B", "DRIVER", "team", 50, "BBB"),
    ]


def test_severe_negative_risk_lowers_race_expectation():
    a, b = drivers()
    safe = {"a": {"R": [30, 35, 40]}, "b": {"R": [20, 18, 22]}}
    with_dnf = {"a": {"R": [30, -20, 40]}, "b": {"R": [20, 18, 22]}}
    safe_points = expected_session_points(a, "R", safe, [a, b], fallback=30)
    risky_points = expected_session_points(a, "R", with_dnf, [a, b], fallback=30)
    assert 0 < risky_points < safe_points < 40
    assert (
        reliability_components(a, "R", with_dnf, [a, b], 30).severe_probability
        > reliability_components(a, "R", safe, [a, b], 30).severe_probability
    )


def test_outlier_race_and_single_negative_sprint_do_not_dominate():
    a, b = drivers()
    history = {"a": {"R": [20, 89, 18], "S": [-10]}, "b": {"R": [15, 18, 20], "S": [9]}}
    race = expected_session_points(a, "R", history, [a, b], fallback=25)
    sprint = expected_session_points(
        a, "S", history, [a, b], fallback=1, race_finish_reference=25
    )
    assert race < (20 + 89 + 18) / 3
    assert -10 < sprint < 9


def test_no_current_season_scores_retain_preweekend_fallback():
    a, b = drivers()
    assert expected_session_points(a, "R", {}, [a, b], fallback=12) == 12
