"""Risk choices use actual payout SD, not payout magnitude or independent podium picks."""

from copy import deepcopy
from itertools import permutations
import math

import numpy as np
import pytest

from f1fantasy import predict, predict_risk as risk
from f1fantasy import predict_data, predict_model, web_predict
from f1fantasy.data import DataError
import test_predict as predict_fixtures

game = predict_fixtures.game


def test_binary_risk_changes_choices_and_boost_without_relabeling_ev(game):
    game["questions"] = game["questions"][1:]
    raw = {}
    for q in game["questions"]:
        q["options"][0]["points"] = 10
        raw[q["id"]] = {"probabilities": {"1": 0.7, "2": 0.3}, "model_type": "test"}
    for name, weight in risk.PROFILES.items():
        result = predict.select(game, raw, risk_aversion=weight)
        for answer in result["answers"]:
            chosen = "2" if name == "high" else "1"
            assert answer["selected_options"] == [chosen]
            multiplier = 2 if answer["booster_id"] == "1" else 1
            mean, sd = (
                (9, 30 * math.sqrt(0.3 * 0.7)) if chosen == "2" else (7, math.sqrt(21))
            )
            assert answer["expected_points"] == pytest.approx(multiplier * mean)
            assert answer["standard_deviation"] == pytest.approx(multiplier * sd)
            assert answer["risk_score"] == pytest.approx(
                multiplier * (mean - weight * sd)
            )
        assert sum(a["booster_id"] == "1" for a in result["answers"]) == 1


def joint(game):
    q = game["questions"][0]
    ranks = np.array([[1, 2, 3, 4], [4, 1, 2, 3], [3, 4, 1, 2], [2, 3, 4, 1]])
    return (
        q,
        ranks,
        {
            **risk.podium_distribution(
                q["options"], range(4), ranks, np.ones_like(ranks, dtype=bool)
            ),
            "model_type": "joint",
        },
    )


def test_publisher_builds_all_risk_profiles_from_one_joint_forecast(game, monkeypatch):
    q, _, podium = joint(game)
    calls = []
    raw = {
        question["id"]: {"probabilities": {"1": 0.7, "2": 0.3}, "model_type": "test"}
        for question in game["questions"]
    }
    raw[q["id"]] = podium

    def forecast(*args, **kwargs):
        calls.append(1)
        return deepcopy(raw)

    monkeypatch.setattr(predict_data, "fetch", lambda season: game)
    monkeypatch.setattr(predict_model, "forecast", forecast)
    monkeypatch.setattr(predict, "pitstop_forecasts", lambda snapshot: {})
    publication = web_predict.build(2099)
    assert publication["status"] == "ready"
    assert calls == [1]
    profiles = publication["recommendation"]["risk_profiles"]
    assert set(profiles) == set(risk.PROFILES)
    for name, result in profiles.items():
        assert result["complete"]
        assert result["risk_aversion"] == risk.PROFILES[name]
        assert len(result["answers"]) == 10
        assert all(
            math.isfinite(a["standard_deviation"]) and math.isfinite(a["risk_score"])
            for a in result["answers"]
        )


@pytest.mark.parametrize("raw_weight", [0, 0.25, 1])
def test_joint_podium_sd_and_optimum_match_full_scoring_with_calibration(
    game, raw_weight
):
    q, ranks, forecast = joint(game)
    raw = np.asarray(list(forecast["position_probabilities"].values()))
    probabilities = raw_weight * raw + (1 - raw_weight) / 4
    moments = risk.podium_moments(q, forecast, probabilities, raw_weight)
    payouts = np.array([o["points"] for o in q["options"]])
    outcomes = [
        (tuple(str(i + 1) for i in np.argsort(r)), raw_weight / len(ranks))
        for r in ranks
    ]
    outcomes += [
        (order, (1 - raw_weight) / 24)
        for order in permutations(["1", "2", "3", "4"], 3)
    ]
    best = -math.inf
    for picks in permutations(range(4), 3):
        selected = [str(i + 1) for i in picks]
        values = [
            (predict.score(q, selected, actual[:3]), weight)
            for actual, weight in outcomes
        ]
        mean = sum(value * weight for value, weight in values)
        sd = math.sqrt(
            max(0, sum(value**2 * weight for value, weight in values) - mean**2)
        )
        assert risk.podium_sd(list(picks), payouts, moments) == pytest.approx(sd)
        best = max(best, mean - 0.5 * sd)
    picks, mean, sd = risk.podium_choice(payouts, moments, 0.5)
    assert mean - 0.5 * sd == pytest.approx(best)
    result = predict.select(game, {q["id"]: forecast}, risk_aversion=0.5)
    answer = result["answers"][0]
    assert answer["expected_points"] - 0.5 * answer[
        "standard_deviation"
    ] == pytest.approx(answer["risk_score"])


def test_risk_boost_uses_score_and_missing_joint_evidence_is_not_invented(game):
    game["questions"] = game["questions"][1:3]
    q1, q2 = game["questions"]
    q1["options"][0]["points"] = 9
    q2["options"][0]["points"] = 10
    raw = {
        q1["id"]: {"probabilities": {"1": 1, "2": 0}, "model_type": "test"},
        q2["id"]: {"probabilities": {"1": 0.95, "2": 0}, "model_type": "test"},
    }
    result = predict.select(game, raw, risk_aversion=0.5)
    assert result["answers"][0]["booster_id"] == "1"
    assert result["answers"][1]["booster_id"] == "0"
    for invalid in [-1, math.nan, math.inf]:
        with pytest.raises(DataError):
            predict.select(game, raw, risk_aversion=invalid)


def test_joint_distribution_includes_no_award_and_rejects_inconsistent_marginals(game):
    q, ranks, forecast = joint(game)
    classified = np.ones_like(ranks, dtype=bool)
    classified[0] = False
    forecast.update(risk.podium_distribution(q["options"], range(4), ranks, classified))
    p = np.asarray(list(forecast["position_probabilities"].values()))
    assert any(row["order"] == [None] * 3 for row in forecast["podium_outcomes"])
    risk.podium_moments(q, forecast, p, 1)
    bad = deepcopy(forecast)
    bad["podium_outcomes"][0]["count"] += 100
    with pytest.raises(DataError, match="disagree"):
        risk.podium_moments(q, bad, p, 1)
