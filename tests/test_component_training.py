from f1fantasy import component_training, feature_training


def example(round_number, actual, source="current_official"):
    values = {
        "baseline": 15.0,
        "fastf1_form": 15.0,
        "official_form": 25.0,
        "recent3": 25.0,
        "team_form": 25.0,
        "circuit_form": 15.0,
        "telemetry_delta": 0,
        "severe_probability": 0.1,
        "classified_points": 25.0,
    }
    return feature_training.Example(
        round_number,
        "DRIVER",
        "race",
        actual,
        15.0,
        feature_training.vector(values),
        source,
    )


def test_severe_probability_and_classified_points_are_calibrated_separately():
    prior = [
        example(i, -20 if i % 5 == 0 else 30, "fastf1_proxy") for i in range(5, 15)
    ]
    weights = component_training.fit(prior)
    assert weights.probability_scale > 1
    assert weights.classified_bias > 0
    forecast, p, classified = component_training.predict(example(1, 25), weights)
    assert 0 < p < 0.5 and classified > 25
    assert forecast > 15


def test_prequential_component_replay_never_uses_target_as_training_input():
    prior = [
        example(i, -20 if i % 5 == 0 else 25, "fastf1_proxy") for i in range(5, 15)
    ]
    current = [example(i, -20 if i % 5 == 0 else 25) for i in range(1, 11)]
    original = component_training.replay(prior, current)
    modified = component_training.replay(prior, current[:-1] + [example(10, 40)])
    assert original["component_weekly"][0] == modified["component_weekly"][0]
    assert original["component_metrics"]["baseline_race_mae"] > 0
    assert "calibrated_brier" in original["component_metrics"]
