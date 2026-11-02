import json
from copy import deepcopy

import numpy as np
import pytest

from f1fantasy import model_fit, racing_model


def rows(objectives):
    """Fold rows whose objective equals the given value (one metric carries it)."""
    return [
        {"winner_brier": v, "pole_brier": 0, "podium_brier": 0, "head_to_head_brier": 0, "nc_brier": 0}
        for v in objectives
    ]


def test_neighbours_move_one_rung_in_one_dimension_and_stay_on_the_ladder():
    params = {"temperature": 0.5, "half_life": 8.0}
    found = model_fit.neighbours(params, ("temperature", "half_life"))
    assert {"temperature": 0.65, "half_life": 8.0} in found
    assert {"temperature": 0.5, "half_life": 6.0} in found
    assert all(0.5 <= p["temperature"] <= 2.0 and p["half_life"] <= 8.0 for p in found)
    assert len(found) == 2  # the lower edge of both ladders has no further step
    # an off-ladder value snaps to its nearest rung before stepping
    snapped = model_fit.neighbours({"temperature": 0.6}, ("temperature",))
    assert {"temperature": 0.5} in snapped and {"temperature": 0.8} in snapped


def test_gate_adopts_a_consistent_gain():
    n = 36
    out, verdict = model_fit.decide({"cur": rows([2.0] * n), "new": rows([1.98] * n)}, "cur")
    assert out == "new" and verdict["adopted"]
    assert verdict["gain_all"] == pytest.approx(0.02)


def test_gate_rejects_a_gain_that_is_below_the_minimum():
    n = 36
    out, verdict = model_fit.decide({"cur": rows([2.0] * n), "new": rows([1.998] * n)}, "cur")
    assert out == "cur" and not verdict["adopted"]


def test_gate_rejects_a_candidate_that_wins_early_but_loses_on_the_latest_races():
    n, hold = 36, model_fit.HOLDOUT
    new = [1.9] * (n - hold) + [2.1] * hold
    out, verdict = model_fit.decide({"cur": rows([2.0] * n), "new": rows(new)}, "cur")
    assert out == "cur" and "latest races" in verdict["reason"]


def test_gate_needs_enough_races():
    out, verdict = model_fit.decide({"cur": rows([2.0] * 10), "new": rows([1.0] * 10)}, "cur")
    assert out == "cur" and "Too few" in verdict["reason"]


def good_fit(**pre):
    params = {"half_life": 3.0, "temperature": 1.0, "team_share": 0.5, "grid_weight": 0.0, "prior": 4.0}
    post = {**params, "grid_weight": 2.5}
    return {
        "schema": 1,
        "pre": {"params": {**params, **pre}},
        "post_qualifying": {"params": post},
        "practice": {"weights": {"Q": 0.1, "SQ": 0.1, "R": 0.05}},
    }


def test_valid_fit_file_is_loaded(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps(good_fit(ret_prior=32.0)))
    fit = racing_model.load_fit(path)
    assert fit["pre"]["half_life"] == 3.0 and fit["practice"]["R"] == 0.05


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema=2),
        lambda d: d["pre"]["params"].update(temperature=99),
        lambda d: d["pre"]["params"].update(half_life="2"),
        lambda d: d["post_qualifying"]["params"].pop("grid_weight"),
        lambda d: d["pre"]["params"].update(ret_prior=0),
        lambda d: d.pop("pre"),
    ],
)
def test_invalid_fit_files_are_ignored(tmp_path, mutate):
    document = good_fit()
    mutate(document)
    path = tmp_path / "p.json"
    path.write_text(json.dumps(document))
    assert racing_model.load_fit(path) is None
    assert racing_model.load_fit(tmp_path / "missing.json") is None
    path.write_text("{not json")
    assert racing_model.load_fit(path) is None


def test_bad_practice_weights_are_dropped_but_params_kept(tmp_path):
    document = good_fit()
    document["practice"]["weights"]["Q"] = 0.9
    path = tmp_path / "p.json"
    path.write_text(json.dumps(document))
    fit = racing_model.load_fit(path)
    assert fit is not None and fit["practice"] is None


def test_shipped_fit_file_is_valid_and_the_loaded_values_are_in_range():
    # Guards the committed data/model-params.json against a bad automated commit.
    if racing_model.PARAMS_FILE.exists():
        assert racing_model.load_fit() is not None
    assert racing_model.BOUNDS["temperature"][0] <= racing_model.PRE_PARAMETERS["temperature"]
    assert racing_model.POST_QUALIFYING_PARAMETERS["grid_weight"] > 0


def test_fit_runs_end_to_end_and_reports_when_data_is_too_thin():
    from tests.test_racing_model import history

    records = history(14)
    document = model_fit.fit(records, simulations=100)
    assert document["schema"] == 1 and document["evaluated_races"] > 0
    assert document["pre"]["decision"]["adopted"] is False
    assert "Too few" in document["pre"]["decision"]["reason"]
    assert document["practice"]["status"].startswith("waiting for data")
    assert document["practice"]["weights"] == racing_model.DEFAULT_PRACTICE
    assert document["log"] and document["log"][-1]["races"] == document["evaluated_races"]
    json.dumps(document, default=float, allow_nan=False)


def test_unchanged_run_does_not_rewrite_the_file():
    a = {"last_race": [2026, 18], "pre": {"params": {"x": 1}}, "post_qualifying": {"params": {"y": 2}}, "practice": {"weights": {"Q": 0.1}}}
    assert model_fit.unchanged(a, deepcopy(a))
    b = deepcopy(a)
    b["pre"]["params"]["x"] = 2
    assert not model_fit.unchanged(a, b)
    assert not model_fit.unchanged(None, a)


def test_practice_weights_are_fitted_once_enough_races_carry_practice_pace():
    from tests.test_racing_model import history

    records = history(30)
    for record in records:
        # practice agrees with the true order, so it is informative evidence
        record["practice_pace"] = {"FP2": {str(j): float(j) * 0.2 - 0.3 for j in range(4)}}
    result = model_fit.fit_practice(records, dict(racing_model.DEFAULT_PRACTICE), simulations=100)
    assert result["status"] == "fitted" and result["folds"] >= model_fit.MIN_PRACTICE_FOLDS
    assert all(0 <= v <= 0.6 for v in result["weights"].values())
    assert result["weights"]["SQ"] == result["weights"]["Q"]
    assert "gain_vs_no_practice" in result


def test_practice_backfill_fills_newest_first_and_does_not_retry_empty_ones_daily():
    from datetime import datetime, timedelta, timezone

    from f1fantasy import practice_archive

    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    records = [
        {"season": 2026, "round": r, "end": (now - timedelta(days=30 - r)).isoformat(),
         "sessions": {"Q": [], "R": []}}
        for r in range(1, 7)
    ]
    document = {"racing": records}
    calls = []

    def loader(season, round_number, fmt):
        calls.append(round_number)
        return {"FP1": {"A": 0.1}} if round_number != 5 else {}

    assert practice_archive.backfill(document, now, limit=3, loader=loader) == 3
    assert calls == [6, 5, 4]  # newest first
    assert records[4]["practice_pace"] == {} and records[4]["practice_checked_at"]
    calls.clear()
    practice_archive.backfill(document, now, limit=3, loader=loader)
    assert calls == [3, 2, 1]  # round 5 (empty) is not retried yet, 4 and 6 are done
    assert not practice_archive.needs_practice(records[4], now)
    assert practice_archive.needs_practice(records[4], now + timedelta(days=31))
