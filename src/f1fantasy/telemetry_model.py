"""Circuit-similarity adjustments learned from cached pre-weekend laps."""

from __future__ import annotations

from math import exp, isfinite
from statistics import median

import fastf1

from .data import Asset, Weekend
from .history import historical_features

TRACK_KEYS = ("speed_kmh", "straight_fraction", "slow_fraction", "braking_fraction")
TRACK_SCALES = (65.0, 0.25, 0.25, 0.20)


def _signature(record: dict) -> tuple[float, ...] | None:
    try:
        values = tuple(float(record["track"][key]) for key in TRACK_KEYS)
    except (KeyError, ValueError, TypeError):
        return None
    return values if all(isfinite(value) for value in values) else None


def _location(value: object) -> str:
    return "".join(char for char in str(value).casefold() if char.isalnum())


def adjustments(
    assets: tuple[Asset, ...], weekends: list[Weekend], *, root=None
) -> dict[tuple[int, str], tuple[float, float, float]]:
    """Return (qualifying, Sprint, race) point deltas for similar tracks.

    Only completed cached sessions before the first target weekend are usable.
    Driver-vs-teammate pace at similar circuits is compared with their baseline
    across all circuits, preventing car performance from dominating the signal.
    """
    if not weekends:
        return {}
    from .history import DEFAULT_CACHE

    records = historical_features(weekends[0].first_session, root or DEFAULT_CACHE)
    eligible = [
        r
        for r in records
        if _signature(r) is not None and not r["track"].get("rainfall", False)
    ]
    if not eligible:
        return {}
    drivers = [asset for asset in assets if asset.kind == "DRIVER"]
    output: dict[tuple[int, str], tuple[float, float, float]] = {}
    for index, weekend in enumerate(weekends):
        from .public_history import event as get_event

        location = _location(get_event(weekend.season, weekend.round)["Location"])
        same_venue = [
            _signature(r) for r in eligible if _location(r["location"]) == location
        ]
        if not same_venue:
            continue
        target = tuple(median(values) for values in zip(*same_venue))

        def similarity(record: dict) -> float:
            signature = _signature(record)
            difference = sum(
                ((left - right) / scale) ** 2
                for left, right, scale in zip(signature, target, TRACK_SCALES)
            )
            return exp(-difference / 2)

        for driver in drivers:
            samples = []
            for record in eligible:
                if record["session"] not in ("Qualifying", "Sprint", "Race"):
                    continue
                info = record["drivers"].get(driver.tla)
                if not info or info.get("teammate_gap_seconds") is None:
                    continue
                pace = float(info.get("pace_seconds", 0))
                gap = float(info["teammate_gap_seconds"])
                if pace <= 0 or not isfinite(gap):
                    continue
                skill = -gap / pace
                weight = (
                    3.0
                    if record["year"] == weekend.season
                    else 1.0
                    if record["year"] == weekend.season - 1
                    else 0.5
                )
                samples.append((skill, similarity(record) * weight, weight))
            if len(samples) < 2:
                continue
            total_weight = sum(raw for _, _, raw in samples)
            similar_weight = sum(weight for _, weight, _ in samples)
            if similar_weight < 0.5:
                continue
            baseline = sum(skill * raw for skill, _, raw in samples) / total_weight
            nearby = (
                sum(skill * weight for skill, weight, _ in samples) / similar_weight
            )
            difference = max(-0.02, min(0.02, nearby - baseline))
            reliability = min(1.0, similar_weight / (similar_weight + 3))
            q = max(-6, min(6, 450 * difference * reliability))
            r = max(-10, min(10, 700 * difference * reliability))
            s = (
                max(-4, min(4, 250 * difference * reliability))
                if weekend.sprint
                else 0.0
            )
            output[index, driver.id] = (q, s, r)
    return output
