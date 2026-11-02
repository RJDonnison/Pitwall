import numpy as np

from f1fantasy import model_compare


def record(grids, positions):
    return {
        "sessions": {
            "R": [
                {"tla": t, "grid": g, "position": p, "classified": True}
                for t, g, p in zip("ABCD", grids, positions)
            ],
            "Q": [
                {"tla": t, "position": q} for t, q in zip("ABCD", (1, 2, 3, 4))
            ],
        }
    }


def test_starting_grid_uses_actual_grid_and_puts_pit_lane_starters_last():
    rec = record((2, 1, 3, 4), (1, 2, 3, 4))
    assert model_compare.starting_grid(rec) == {"A": 2, "B": 1, "C": 3, "D": 4}
    rec["sessions"]["R"][0]["grid"] = None  # pit-lane start
    assert model_compare.starting_grid(rec)["A"] == 5


def test_starting_grid_falls_back_to_qualifying_when_grid_missing():
    rec = record((None,) * 4, (1, 2, 3, 4))
    assert model_compare.starting_grid(rec) == {"A": 1, "B": 2, "C": 3, "D": 4}


def test_paired_interval_covers_the_mean_and_detects_a_constant_gain():
    a = [{"x": 1.0 + 0.1 * i} for i in range(20)]
    b = [{"x": r["x"] - 0.2} for r in a]
    mean, lo, hi = model_compare.paired(a, b, "x")
    assert abs(mean + 0.2) < 1e-9 and lo <= mean <= hi and hi < 0
