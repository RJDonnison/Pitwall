"""Question-level payout dispersion, retaining mutually exclusive podium outcomes."""

from itertools import permutations

import numpy as np

from .data import DataError

PROFILES = {"low": 0.5, "medium": 0.25, "high": 0.1}


def podium_distribution(options, indices, ranks, classified):
    outcomes = np.full((len(ranks), 3), -1, dtype=int)
    probabilities = {}
    for option_index, (option, driver) in enumerate(zip(options, indices)):
        probabilities[option["id"]] = []
        for slot in range(3):
            mask = (ranks[:, driver] == slot + 1) & classified[:, driver]
            probabilities[option["id"]].append(float(mask.mean()))
            outcomes[mask, slot] = option_index
    unique, counts = np.unique(outcomes, axis=0, return_counts=True)
    return {
        "position_probabilities": probabilities,
        "podium_outcomes": [
            {
                "order": [options[i]["id"] if i >= 0 else None for i in order],
                "count": int(count),
            }
            for order, count in zip(unique, counts)
        ],
    }


def podium_moments(question, forecast, probabilities, raw_weight):
    """Mix joint raw and uniform distributions using the probability calibration weight."""
    ids = [o["id"] for o in question["options"]]
    valid_ids = set(ids)
    index = {ident: i for i, ident in enumerate(ids)}
    rows = forecast["podium_outcomes"]
    orders, counts = [], []
    for row in rows:
        order = row["order"]
        present = [i for i in order if i is not None]
        if (
            len(order) != 3
            or len(set(present)) != len(present)
            or not set(present) <= valid_ids
            or not isinstance(row["count"], int)
            or row["count"] <= 0
        ):
            raise DataError("Invalid joint Predict podium outcomes")
        orders.append([index[i] if i is not None else -1 for i in order])
        counts.append(row["count"])
    if not orders:
        raise DataError("Missing joint Predict podium outcomes")

    def features(orders):
        orders = np.asarray(orders)
        actual = np.zeros((len(orders), len(ids), 3))
        for slot in range(3):
            positions = orders[:, slot]
            valid = positions >= 0
            actual[np.flatnonzero(valid), positions[valid], slot] = 1
        return actual, (actual.sum(axis=2)[:, :, None] + actual).reshape(
            len(orders), -1
        )

    actual, values = features(orders)
    weights = np.asarray(counts, dtype=float) / sum(counts)
    raw = np.asarray([forecast["position_probabilities"][i] for i in ids])
    if not np.allclose(np.einsum("s,sij->ij", weights, actual), raw, atol=1e-8):
        raise DataError("Joint Predict podium outcomes disagree with probabilities")
    second = raw_weight * (values.T @ (weights[:, None] * values))
    if raw_weight < 1:
        _, uniform = features(list(permutations(range(len(ids)), 3)))
        second += (1 - raw_weight) * (uniform.T @ uniform / len(uniform))
    mean = (probabilities.sum(axis=1)[:, None] + probabilities).ravel()
    return mean, second - np.outer(mean, mean)


def podium_choice(payouts, moments, risk_aversion):
    """Evaluate every legal distinct-driver assignment against its joint payout SD."""
    mean, covariance = moments
    choices = np.asarray(list(permutations(range(len(payouts)), 3)))
    indices = choices * 3 + np.arange(3)
    amounts = payouts[choices]
    ev = (mean[indices] * amounts).sum(axis=1)
    variance = np.zeros(len(choices))
    for a in range(3):
        for b in range(3):
            variance += (
                amounts[:, a] * amounts[:, b] * covariance[indices[:, a], indices[:, b]]
            )
    sd = np.sqrt(np.maximum(0, variance))
    best = int(np.argmax(ev - risk_aversion * sd))
    return choices[best].tolist(), float(ev[best]), float(sd[best])


def podium_sd(picks, payouts, moments):
    indices = np.asarray(picks) * 3 + np.arange(3)
    amounts = payouts[picks]
    return float(
        np.sqrt(max(0, amounts @ moments[1][np.ix_(indices, indices)] @ amounts))
    )
