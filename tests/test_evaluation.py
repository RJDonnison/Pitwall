from f1fantasy.backtest import BacktestAsset
from f1fantasy.evaluation import selection_metrics
from f1fantasy.projections import Estimate


def test_rank_overlap_boost_and_unbudgeted_regret():
    drivers = [
        BacktestAsset(
            str(i),
            f"Driver {i}",
            "DRIVER",
            Estimate(0, 0, 10 - i),
            Estimate(0, 0, 15 if i == 5 else 10 - i),
        )
        for i in range(6)
    ]
    teams = [
        BacktestAsset(
            f"c{i}",
            f"Team {i}",
            "CONSTRUCTOR",
            Estimate(0, 0, 10 - i),
            Estimate(0, 0, 15 if i == 2 else 10 - i),
        )
        for i in range(3)
    ]
    metrics = selection_metrics(tuple(drivers + teams))
    assert metrics["drivers"]["top_pick_overlap"] == 4
    assert metrics["drivers"]["unbudgeted_points_regret"] == 9
    assert metrics["drivers"]["boost_regret_within_predicted_five"] == 0
    assert metrics["constructors"]["top_pick_overlap"] == 1
    assert metrics["constructors"]["unbudgeted_points_regret"] == 6


def test_boost_regret_when_another_selected_driver_outscores_boost():
    drivers = [
        BacktestAsset(
            str(i),
            f"D{i}",
            "DRIVER",
            Estimate(0, 0, 10 - i),
            Estimate(0, 0, 1 if i == 0 else 12 - i),
        )
        for i in range(6)
    ]
    metrics = selection_metrics(tuple(drivers))
    assert metrics["drivers"]["boost_regret_within_predicted_five"] == 10
    assert metrics["constructors"] is None
