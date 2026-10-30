from datetime import datetime, timezone

import pytest

from f1fantasy import accuracy
from f1fantasy.data import Asset

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
MODEL = dict(telemetry=True, risk=True, fantasy={"model": "test-v1", "groups": {}})
ASSETS = [Asset("1", "Alpha", "DRIVER", "a", 100)]


def event(round, error=2, sprint=False, interval=None):
    return dict(
        season=2026,
        round=round,
        model=MODEL,
        sprint=sprint,
        assets=[dict(id="1", name="Alpha", kind="DRIVER")],
        forecasts={"1": [10 + error, 5 + error if sprint else 0, 20 + error]},
        actual={"1": [10, 5 if sprint else 0, 20]},
        baseline={"1": [20, 10 if sprint else 0, 30]},
        intervals={"1": {"Q": interval, "R": interval}} if interval else {},
        generated_at=f"2026-09-{round:02d}T10:00:00+00:00",
        completed_at=f"2026-09-{round:02d}T20:00:00+00:00",
    )


def test_sparse_history_has_errors_but_no_false_confidence_or_ranges():
    r = accuracy.report([event(1)], MODEL, NOW)
    q = r["groups"]["DRIVER/Q/regular"]
    assert q["mae"] == 2 and q["baseline_mae"] == 10
    assert q["confidence"] == "Insufficient history"
    assert q["radius"] is None and q["coverage_observations"] == 0
    assert accuracy.intervals(ASSETS, {"1": [10, 0, 20]}, False, r) == {"1": {}}


def test_ranges_use_weekend_blocks_and_do_not_calibrate_on_their_own_result():
    earlier = [event(i, error=i) for i in range(1, 9)]
    r = accuracy.report(earlier, MODEL, NOW)
    bands = accuracy.intervals(ASSETS, {"1": [10, 0, 20]}, False, r)
    assert bands["1"]["Q"]["low"] == 2
    assert bands["1"]["Q"]["high"] == 18
    assert r["groups"]["DRIVER/Q/regular"]["confidence"] == "Provisional range"
    assert "S" not in bands["1"]
    next_event = event(9, error=100, interval=bands["1"]["Q"])
    checked = accuracy.report(earlier + [next_event], MODEL, NOW)
    assert checked["history"][-2]["interval"]["high"] == 18
    assert checked["groups"]["DRIVER/Q/regular"]["coverage_hits"] == 1
    assert checked["groups"]["DRIVER/R/regular"]["coverage_hits"] == 0
    # Many correlated assets on a single weekend cannot unlock a range.
    e = event(1)
    for i in range(2, 25):
        key = str(i)
        e["assets"].append(dict(id=key, name=key, kind="DRIVER"))
        e["forecasts"][key] = [99, 0, 99]
        e["actual"][key] = [10, 0, 20]
    assert (
        accuracy.report([e], MODEL, NOW)["groups"]["DRIVER/Q/regular"]["radius"] is None
    )


def test_sprint_and_model_version_evidence_are_separate():
    data = [event(i) for i in range(1, 9)] + [event(9, sprint=True)]
    r = accuracy.report(data, MODEL, NOW)
    assert r["groups"]["DRIVER/R/sprint"]["weekends"] == 1
    assert r["groups"]["DRIVER/S/sprint"]["radius"] is None
    changed = {**MODEL, "fantasy": {"model": "test-v2", "groups": {}}}
    assert accuracy.report(data, changed, NOW)["status"] == "insufficient_history"
    assert (
        accuracy.report(data, {**MODEL, "weather": "weather-analogue-v2"}, NOW)[
            "status"
        ]
        == "insufficient_history"
    )


def test_baseline_excludes_later_and_other_format_results():
    document = dict(fantasy_events={}, fantasy={}, racing=[])
    for n, sprint, score in (
        (1, False, 10),
        (2, False, 20),
        (3, False, 30),
        (4, False, 40),
        (5, True, 900),
        (31, False, 10000),
    ):
        end = f"2026-10-{n:02d}T12:00:00+00:00"
        document["fantasy_events"][str(n)] = end
        document["fantasy"][str(n)] = [
            dict(
                PlayerId=1,
                QualifyingPoints=score,
                SprintPoints=0,
                GamedayPoints=score + 10,
            )
        ]
        document["racing"].append(
            dict(end=end, sessions={"R": [], **({"S": []} if sprint else {})})
        )
    b = accuracy.baseline(ASSETS, document, NOW, False)
    assert b["1"] == pytest.approx([30, 0, 10])


def test_forward_checked_label_requires_later_weekends_not_just_many_assets():
    interval = dict(low=0, high=40, calibration_weekends=8, method=accuracy.VERSION)
    data = [event(i, interval=interval) for i in range(9, 17)]
    q = accuracy.report(data, MODEL, NOW)["groups"]["DRIVER/Q/regular"]
    assert q["confidence"] == "Forward checked"
    assert q["coverage_hits"] == 8 and q["coverage_weekends"] == 8
