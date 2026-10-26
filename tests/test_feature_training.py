import pytest

from f1fantasy import feature_training
from f1fantasy.data import DataError


def example(round_number, actual, source="current_official"):
    values = {
        "baseline": 10.0,
        "fastf1_form": 10.0,
        "official_form": 20.0,
        "recent3": 20.0,
        "team_form": 20.0,
        "circuit_form": 10.0,
        "telemetry_delta": 0,
        "severe_probability": 0.1,
        "classified_points": 20.0,
    }
    return feature_training.Example(
        round_number,
        "DRIVER",
        "race",
        actual,
        10.0,
        feature_training.vector(values),
        source,
    )


def test_feature_model_learns_and_replays_without_current_race_leakage():
    prior = [example(round_number, 10, "fastf1_proxy") for round_number in range(4, 12)]
    current = [example(round_number, 20) for round_number in range(1, 10)]
    report = feature_training.replay(prior, current)
    assert report["feature_active"]
    assert report["feature_metrics"]["DRIVER"]["race"]["feature_mae"] < 10
    assert report["feature_weekly"][0]["errors"]["DRIVER.race"]["prior_examples"] == 8
    changed = current[:-1] + [example(9, -20)]
    other = feature_training.replay(prior, changed)
    assert report["feature_weekly"][0] == other["feature_weekly"][0]


def test_feature_vector_is_validated_and_predictions_are_bounded():
    values = {
        "baseline": 10.0,
        "fastf1_form": 12.0,
        "official_form": 15.0,
        "recent3": 16.0,
        "team_form": 13.0,
        "circuit_form": 14.0,
        "telemetry_delta": 2.0,
        "severe_probability": 0.2,
        "classified_points": 18.0,
    }
    prediction = feature_training.apply(10, values, "race", [20.0] + [0] * 8)
    assert prediction == 18  # cap the size of a trained adjustment
    values["severe_probability"] = float("nan")
    with pytest.raises(DataError, match="Non-finite"):
        feature_training.vector(values)


def test_replay_reports_pre_result_unbudgeted_ranking_and_boost():
    week = []
    for kind, count in (("DRIVER", 6), ("CONSTRUCTOR", 3)):
        for index in range(count):
            id_ = f"{kind}{index}"
            score = 10 - index
            actual = 15 if index == count - 1 else score
            for phase in ("qualifying", "race"):
                week.append(
                    feature_training.Example(
                        1,
                        kind,
                        phase,
                        actual if phase == "race" else 0,
                        score if phase == "race" else 0,
                        (1.0,) + (0.0,) * (len(feature_training.FEATURE_NAMES) - 1),
                        asset_id=id_,
                    )
                )
    fitted = {
        (kind, phase): [0.0] * len(feature_training.FEATURE_NAMES)
        for kind in ("DRIVER", "CONSTRUCTOR")
        for phase in ("qualifying", "race")
    }
    ranking = feature_training.ranking_diagnostics(week, fitted)
    assert ranking["baseline"]["drivers"]["top_pick_overlap"] == 4
    assert ranking["baseline"]["drivers"]["unbudgeted_points_regret"] > 0
    assert "boost_regret_within_predicted_five" in ranking["trained"]["drivers"]
