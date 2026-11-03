"""Expected Predict points, constrained answer selection and prequential evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import account as storage, predict_data as data, predict_model
from .data import DataError


def _vector(question, forecast):
    """Validate normalized probabilities without converting payout hints to odds."""
    ids = [o["id"] for o in question["options"]]
    if question["template"] == 1:
        raw = forecast["position_probabilities"]
        matrix = np.array([raw[i] for i in ids], dtype=float)
        if (
            matrix.shape != (len(ids), 3)
            or not np.all(np.isfinite(matrix))
            or np.any(matrix < 0)
            or np.any(matrix > 1)
            or np.any(matrix.sum(axis=0) > 1.000001)
            or np.any(matrix.sum(axis=1) > 1.000001)
        ):
            raise DataError("Invalid Predict ordered podium probabilities")
        return matrix
    raw = forecast["probabilities"]
    vector = np.array([raw[i] for i in ids], dtype=float)
    if (
        not np.all(np.isfinite(vector))
        or np.any(vector < 0)
        or np.any(vector > 1)
        or vector.sum() > 1.000001
    ):
        raise DataError("Invalid Predict answer probabilities")
    return vector


def _target(question, ids):
    targets = np.zeros(
        (len(question["options"]), 3)
        if question["template"] == 1
        else len(question["options"])
    )
    positions = {o["id"]: i for i, o in enumerate(question["options"])}
    if (
        len(set(ids)) != len(ids)
        or not set(ids) <= set(positions)
        or (question["template"] == 1 and len(ids) != 3)
        or (question["template"] != 1 and len(ids) > 1)
    ):
        raise DataError("Invalid Predict outcome labels")
    for slot, ident in enumerate(ids):
        if targets.ndim == 2:
            targets[positions[ident], slot] = 1
        else:
            targets[positions[ident]] = 1
    return targets


def _uniform(vector):
    return np.full_like(vector, 1 / len(vector))


def _brier(probabilities, target):
    loss = float(np.square(probabilities - target).sum())
    if probabilities.ndim == 1:
        # Both H2H drivers can fail to classify, yielding an explicit no-award
        # outcome rather than forcing option probabilities to sum to one.
        loss += float((probabilities.sum() - target.sum()) ** 2)
    return loss


def _calibrate(question, forecast, training, cutoff):
    """Fit a conservative mixture on earlier settled, pre-lock forecast archives.

    A convex blend preserves podium marginal constraints. Twenty observed
    outcomes are required before fitting; zero data is explicitly uncalibrated.
    """
    vector = _vector(question, forecast)
    examples = []
    seen = set()
    for row in sorted(training, key=lambda row: data.utc(row["observed_at"])):
        if not row.get("settled_at") or data.utc(row["settled_at"]) >= cutoff:
            continue
        for q in row["snapshot"]["questions"]:
            identity = (
                row["snapshot"]["season"],
                row["snapshot"]["scope"],
                row["snapshot"]["gameday_id"],
                q["id"],
            )
            if identity in seen:
                continue
            f = row["forecast"].get(str(q["id"]), row["forecast"].get(q["id"], {}))
            if (
                f.get("model_type") == forecast.get("model_type")
                and "unsupported" not in f
                and (q["template"] == 1) == (question["template"] == 1)
            ):
                seen.add(identity)
                examples.append(
                    (_vector(q, f), _target(q, row["labels"][str(q["id"])]))
                )
    weight = 1.0
    if len(examples) >= 20:
        weight = min(
            (0.0, 0.25, 0.5, 0.75, 1.0),
            key=lambda w: (
                sum(_brier(w * p + (1 - w) * _uniform(p), y) for p, y in examples)
                + 2 * (1 - w) ** 2
            ),
        )
    calibrated = weight * vector + (1 - weight) * _uniform(vector)
    return calibrated, {
        "method": "chronological_uniform_mixture"
        if len(examples) >= 20
        else "uncalibrated_insufficient_prelock_archives",
        "training_outcomes": len(examples),
        "raw_weight": weight,
        "cutoff_utc": cutoff.isoformat(),
    }


def score(question, selected, actual, boosted=False):
    points = {o["id"]: o["points"] for o in question["options"]}
    if question["template"] == 1:
        total = sum(
            points[i]
            * (int(i in actual) + int(slot < len(actual) and actual[slot] == i))
            for slot, i in enumerate(selected)
        )
    elif question["choice_limit"] == 1:
        total = sum(points[i] for i in selected if i in actual)
    else:
        raise DataError("Unestablished Predict multi-answer scoring contract")
    return total * (2 if boosted else 1)


def select(snapshot, forecasts, training=()):
    answers, unsupported = [], []
    cutoff = min(
        data.utc(snapshot["first_session_utc"]), data.utc(snapshot["fetched_at"])
    )
    for q in snapshot["questions"]:
        forecast = forecasts.get(q["id"], forecasts.get(str(q["id"]), {}))
        if "unsupported" in forecast or not forecast:
            unsupported.append(
                {
                    "question_id": q["id"],
                    "text": q["text"],
                    "reason": forecast.get(
                        "unsupported", "No established question model"
                    ),
                }
            )
            continue
        if q["template"] != 1 and q["choice_limit"] != 1:
            unsupported.append(
                {
                    "question_id": q["id"],
                    "text": q["text"],
                    "reason": "Multi-selection scoring beyond the ordered podium is unverified",
                }
            )
            continue
        probabilities, calibration = _calibrate(q, forecast, training, cutoff)
        payouts = np.array([o["points"] for o in q["options"]])
        if q["template"] == 1:
            expected = payouts[:, None] * (
                probabilities.sum(axis=1)[:, None] + probabilities
            )
            slots, indexes = linear_sum_assignment(-expected.T)
            picks = [int(indexes[list(slots).index(slot)]) for slot in range(3)]
            points = float(sum(expected[i, slot] for slot, i in enumerate(picks)))
        else:
            index = int(np.argmax(payouts * probabilities))
            picks, points = [index], float((payouts * probabilities)[index])
        answers.append(
            {
                "question_id": q["id"],
                "text": q["text"],
                "selected_options": [q["options"][i]["id"] for i in picks],
                "selected_names": [q["options"][i]["name"] for i in picks],
                "booster_id": "0",
                "expected_points_before_boost": points,
                "expected_points": points,
                "probabilities": {
                    o["id"]: probabilities[i].tolist()
                    if probabilities.ndim == 2
                    else float(probabilities[i])
                    for i, o in enumerate(q["options"])
                },
                "calibration": calibration,
                "model_type": forecast["model_type"],
                "evidence": forecast.get("evidence", {}),
            }
        )
    if answers:
        boosted = max(answers, key=lambda r: r["expected_points"])
        boosted["booster_id"] = "1"
        boosted["expected_points"] *= 2
    result = {
        k: snapshot[k]
        for k in (
            "season",
            "scope",
            "gameday_id",
            "race_id",
            "first_session_utc",
            "fetched_at",
            "deadline_utc",
            "deadline_authority",
            "locked",
        )
    }
    result.update(
        question_fingerprint=data.fingerprint(snapshot),
        complete=not unsupported and len(answers) == 10,
        answers=answers,
        unsupported=unsupported,
        expected_total_points=sum(a["expected_points"] for a in answers),
        warnings=[
            "Model forecasts are uncertain; payouts are used only for scoring. Raw probabilities stay explicitly uncalibrated until sufficient earlier settled pre-lock archives exist."
        ],
    )
    if result["complete"]:
        data.validate_answers(snapshot, answers)
    return result


def _published_at(body):
    try:
        return datetime.strptime(
            body["Meta"]["Timestamp"]["UTCTime"], "%m/%d/%Y %I:%M:%S %p"
        ).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        raise DataError("Cannot verify historical Predict publication time") from None


def pitstop_forecasts(snapshot):
    """Stationary-stop winners from finalized Predict labels, not pit-lane time.

    Whole-race fastest-stop labels are a distinct prior and cannot be inferred
    from FastF1's total pit-lane transit time. Only already published labels count.
    """
    qs = [
        q
        for q in snapshot["questions"]
        if re.search(r"fastest pit\s?stop", q["text"], re.I)
    ]
    if not qs or snapshot["scope"] != "round":
        return {}
    cutoff = data.utc(snapshot["first_session_utc"])
    fixtures = [
        r
        for r in snapshot["season_fixtures"]
        if data.utc(r["SessionEndDateISO8601"]) < cutoff and int(r["MatchStatus"]) == 4
    ]
    ids = sorted({int(r["GamedayId"]) for r in fixtures})[-8:]
    winners, contributing = [], []
    for day in ids:
        body = data.get(f"questions/questions_{day}_en.json")
        if _published_at(body) >= cutoff:
            continue
        for raw in data.value(body)["Questions"]:
            if (
                re.search(r"fastest pit\s?stop", raw["Text"], re.I)
                and int(raw["Status"]) == 4
                and len(raw["Answer"]) == 1
                and int(raw["Answer"][0]["Type"]) == 2
            ):
                winners.append(str(raw["Answer"][0]["Id"]))
                contributing.append(day)
    if not winners:
        return {
            q["id"]: {
                "unsupported": "No finalized pre-cutoff official fastest stationary-stop labels"
            }
            for q in qs
        }
    return {
        q["id"]: {
            "probabilities": {
                o["id"]: (1 + winners.count(o["id"]))
                / (len(q["options"]) + len(winners))
                for o in q["options"]
            },
            "model_type": "official_stationary_stop_winner_dirichlet",
            "evidence": {
                "gamedays": contributing,
                "cutoff": cutoff.isoformat(),
                "prior_per_team": 1,
                "calibrated": False,
            },
        }
        for q in qs
    }


def archive_directory(directory):
    return Path(directory) / "predict" / "research"


def archives(directory):
    root = archive_directory(directory)
    if not root.exists():
        return []
    rows = []
    with storage._locked(root):
        for path in sorted(root.glob("*.json")):
            row = storage._read_json(path)
            try:
                if (
                    row["checksum"] != storage._checksum(row)
                    or row["fingerprint"] != data.fingerprint(row["snapshot"])
                    or data.utc(row["observed_at"])
                    >= data.utc(row["snapshot"]["first_session_utc"])
                    or row["snapshot"]["locked"]
                ):
                    raise ValueError
                if row.get("settled_at") and (
                    data.utc(row["settled_at"])
                    <= data.utc(row["snapshot"]["last_session_utc"])
                    or not isinstance(row["labels"], dict)
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise DataError(
                    "Invalid point-in-time Predict archive; no historical scoring"
                ) from None
            rows.append(row)
    return rows


def recommend(
    snapshot, *, directory=None, simulations=4000, seed=2026, use_telemetry=True
):
    if snapshot["locked"] or datetime.now(timezone.utc) >= data.utc(
        snapshot["first_session_utc"]
    ):
        raise DataError(
            "Predict forecast is pre-weekend only; current/elapsed results cannot become predictions"
        )
    raw = predict_model.forecast(
        snapshot, simulations=simulations, seed=seed, use_telemetry=use_telemetry
    )
    raw.update(pitstop_forecasts(snapshot))
    # JSON object keys are strings. Normalize before checksumming so question
    # 10 does not change canonical ordering on a save/load round trip.
    raw = {str(key): value for key, value in raw.items()}
    training = archives(directory) if directory is not None else []
    result = select(snapshot, raw, training)
    if directory is not None:
        # Persist public inputs and forecasts only; authenticated cookies/GUIDs and
        # saved selections are deliberately absent from research snapshots.
        public = {
            k: snapshot[k]
            for k in (
                "season",
                "scope",
                "gameday_id",
                "race_id",
                "first_session_utc",
                "last_session_utc",
                "fetched_at",
                "deadline_utc",
                "deadline_authority",
                "locked",
                "questions",
                "roster",
                "fixtures",
                "season_fixtures",
            )
        }
        row = {
            "version": 1,
            "snapshot": public,
            "fingerprint": data.fingerprint(public),
            "forecast": raw,
            "observed_at": public["fetched_at"],
            "labels": None,
            "settled_at": None,
        }
        row["checksum"] = storage._checksum(row)
        name = f"{public['season']}-{public['scope']}-{public['gameday_id']}-{row['fingerprint']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json"
        with storage._locked(archive_directory(directory)) as root:
            storage._atomic(root / name, row)
    return result


def settle(directory):
    """Attach new final labels without changing the original pre-lock snapshot."""
    rows = archives(directory)
    changed = 0
    root = archive_directory(directory)
    for row in rows:
        if row.get("settled_at") or datetime.now(timezone.utc) <= data.utc(
            row["snapshot"]["last_session_utc"]
        ):
            continue
        actual = data.labels(row["snapshot"])
        row.update(labels=actual, settled_at=datetime.now(timezone.utc).isoformat())
        row["checksum"] = storage._checksum(row)
        with storage._locked(root):
            for path in root.glob("*.json"):
                old = storage._read_json(path)
                if (
                    old.get("observed_at") == row["observed_at"]
                    and old.get("fingerprint") == row["fingerprint"]
                ):
                    storage._atomic(path, row)
                    changed += 1
                    break
    return {"settled_archives": changed}


def backtest(directory):
    """Walk forward over actual archived pre-lock forecasts and later outcomes."""
    rows = archives(directory)
    settled = sorted(
        (r for r in rows if r.get("settled_at")),
        key=lambda r: data.utc(r["observed_at"]),
    )
    if not settled:
        raise DataError(
            "No settled point-in-time Predict archives; archive recommendations before lock, then run predict settle after official results"
        )
    report, training, used = [], [], set()
    for row in settled:
        key = (
            row["snapshot"]["season"],
            row["snapshot"]["scope"],
            row["snapshot"]["gameday_id"],
        )
        if key in used:
            continue
        used.add(key)
        # Each round contributes once: earliest archived pre-lock forecast.
        result = select(row["snapshot"], row["forecast"], training)
        questions = {q["id"]: q for q in row["snapshot"]["questions"]}
        details = []
        for answer in result["answers"]:
            q = questions[answer["question_id"]]
            actual = row["labels"][str(q["id"])]
            p = np.array([answer["probabilities"][o["id"]] for o in q["options"]])
            target = _target(q, actual)
            brier = _brier(p, target)
            baseline = _brier(_uniform(p), target)
            indices = {o["id"]: i for i, o in enumerate(q["options"])}
            likelihood = [
                p[indices[i], slot] if p.ndim == 2 else p[indices[i]]
                for slot, i in enumerate(actual)
            ]
            if not actual and p.ndim == 1:
                likelihood = [max(0.0, 1 - float(p.sum()))]
            details.append(
                {
                    "question_id": q["id"],
                    "model_type": answer["model_type"],
                    "points": score(
                        q,
                        answer["selected_options"],
                        actual,
                        answer["booster_id"] == "1",
                    ),
                    "expected_points": answer["expected_points"],
                    "brier": brier,
                    "uniform_brier": baseline,
                    "log_loss": -sum(
                        math.log(max(1e-12, float(v))) for v in likelihood
                    ),
                    "calibration": answer["calibration"],
                }
            )
        report.append(
            {
                "season": key[0],
                "scope": key[1],
                "gameday_id": key[2],
                "observed_at": row["observed_at"],
                "settled_at": row["settled_at"],
                "complete": result["complete"],
                "questions": details,
                "total_points": sum(d["points"] for d in details),
            }
        )
        training.append(row)
    groups = {}
    for row in report:
        for q in row["questions"]:
            group = groups.setdefault(
                q["model_type"],
                {
                    "questions": 0,
                    "points": 0,
                    "brier_sum": 0,
                    "uniform_brier_sum": 0,
                    "log_loss_sum": 0,
                },
            )
            group["questions"] += 1
            group["points"] += q["points"]
            group["brier_sum"] += q["brier"]
            group["uniform_brier_sum"] += q["uniform_brier"]
            group["log_loss_sum"] += q["log_loss"]
    for group in groups.values():
        for metric in ("brier", "uniform_brier", "log_loss"):
            group["mean_" + metric] = group.pop(metric + "_sum") / group["questions"]
    return {
        "method": "chronological_archived_prelock_forecasts",
        "rounds": report,
        "total_points": sum(r["total_points"] for r in report),
        "question_count": sum(len(r["questions"]) for r in report),
        "by_model_type": groups,
        "limitations": [
            "Historical public result feeds alone do not prove pre-lock payouts/options. Only saved pre-lock inputs/forecasts are scored. Small-sample calibration is reported rather than represented as validated improvement."
        ],
    }
