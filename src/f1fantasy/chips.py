"""Empirical chip inputs and a future-only, pure Final Fix decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import TYPE_CHECKING

from . import data
from .data import Asset, DataError, Weekend
from .projections import Estimate

if TYPE_CHECKING:
    from .optimizer import Lineup

CHIPS = frozenset(
    {"autopilot", "x3", "no_negative", "wildcard", "limitless", "final_fix"}
)
PREWEEK_CHIPS = CHIPS - {"final_fix"}


def components(value: Estimate) -> tuple[float, float, float]:
    return value.qualifying, value.sprint, value.race


def valid_estimate(value: Estimate) -> bool:
    return all(isfinite(n) for n in components(value)) and isfinite(value.total)


def no_negative_uplift(value: Estimate) -> Estimate:
    """Floor each session at zero without increasing positive forecasts."""
    return Estimate(*(max(0.0, -n) for n in components(value)))


@dataclass(frozen=True)
class ChipValues:
    """Keys are zero-based horizon indices, not championship round numbers.

    No Negative values report zero-floor *uplifts*, not adjusted forecasts.
    Optimizers derive the floor directly from forecasts. Autopilot scenarios
    contain correlated driver session outcomes, with means equal to forecasts.
    Missing eligible Autopilot inputs are an error.
    """

    no_negative: dict[tuple[int, str], Estimate] = field(default_factory=dict)
    autopilot: dict[int, tuple[dict[str, Estimate], ...]] = field(default_factory=dict)
    history_gamedays: dict[int, tuple[int, ...]] = field(default_factory=dict)
    skipped_history_gamedays: tuple[int, ...] = ()
    # Assets without same-format history have neutral Autopilot scenarios.
    imputed_assets: tuple[str, ...] = ()
    joint: dict[int, tuple[dict[str, dict[str, Estimate]], ...]] = field(
        default_factory=dict
    )


# The official feed names the Sprint scoring session "Sprint Qualifying".
SESSION_ALIASES = {"Sprint Qualifying": "Sprint"}
# At most this many assets may lack history (a new driver or team); more is a roster
# or feed fault and still fails.
MAX_IMPUTED = 2


def load_chip_values(
    assets: tuple[Asset, ...],
    weekends: list[Weekend],
    estimates: dict[tuple[int, str], Estimate],
) -> ChipValues:
    """Use at most five completed same-format official current-season weekends.

    All samples precede the *first* forecast weekend, even for later horizons.
    No Negative floors each forecast/session scenario at zero. Historical
    category-adjusted nonegative_points are not used to inflate positive scores.
    """
    if not weekends or any(w.season != weekends[0].season for w in weekends):
        raise DataError("Chip history requires one nonempty season horizon")
    cutoff = min(weekends[0].first_session, datetime.now(timezone.utc))
    history = sorted(
        (
            w
            for w in data.season_weekends(weekends[0].season)
            if w.season == weekends[0].season
            and w.last_session is not None
            and w.last_session < cutoff
            and w.first_session < cutoff
        ),
        key=lambda w: w.first_session,
    )
    samples: dict[bool, list[dict[str, Estimate]]] = {}
    sampled: dict[bool, list[int]] = {}
    skipped: list[int] = []
    for sprint in {w.sprint for w in weekends}:
        matching = [w for w in history if w.sprint == sprint][-5:]
        if not matching:
            raise DataError("No completed same-format chip history before forecast")
        samples[sprint] = []
        sampled[sprint] = []
        for weekend in matching:
            scores: dict[str, Estimate] = {}
            try:
                from .public_history import fantasy_feed

                rows = fantasy_feed(
                    f"drivers/{weekend.gameday_id}_en.json", data._get_json
                )["Value"]
                active = {a.id: a for a in assets}
                # An official null is unavailable history, never zero points.
                # Exclude the entire joint sample so drivers stay correlated.
                if any(
                    session["points"] is None
                    for item in rows
                    if str(item["PlayerId"]) in active
                    for session in item["SessionWisePoints"]
                ):
                    skipped.append(weekend.gameday_id)
                    continue
                for item in rows:
                    key = str(item["PlayerId"])
                    if key not in active:
                        continue
                    if key in scores or item["PositionName"] != active[key].kind:
                        raise DataError("Duplicate or mismatched chip-history asset")
                    points = [0.0, 0.0, 0.0]
                    seen = set()
                    expected = {"Qualifying", "Race"} | (
                        {"Sprint"} if sprint else set()
                    )
                    for session in item["SessionWisePoints"]:
                        kind = SESSION_ALIASES.get(
                            session["sessiontype"], session["sessiontype"]
                        )
                        if kind not in expected or kind in seen:
                            raise DataError(
                                "Unexpected or duplicate chip-history session"
                            )
                        seen.add(kind)
                        index = {"Qualifying": 0, "Sprint": 1, "Race": 2}[kind]
                        points[index] = float(session["points"])
                    score = Estimate(*points)
                    if (
                        seen != expected
                        or not valid_estimate(score)
                        or not isfinite(float(item["GamedayPoints"]))
                        or abs(score.total - float(item["GamedayPoints"])) > 1e-6
                    ):
                        raise DataError(
                            "Incomplete or inconsistent chip-history scores"
                        )
                    scores[key] = score
                if not scores:
                    raise DataError("Chip history contains no active asset")
            except (KeyError, TypeError, ValueError) as exc:
                raise DataError(
                    f"Unverifiable chip history for {weekend.name}: {exc}"
                ) from exc
            samples[sprint].append(scores)
            sampled[sprint].append(weekend.gameday_id)
        if not samples[sprint]:
            raise DataError(
                "No complete common same-format chip history before forecast"
            )
    # A new driver or team is absent from older gamedays. Give it its own mean over
    # the samples that contain it, or a neutral value when it has none, so one new
    # asset cannot disable the chips for everyone. Wider gaps are still an error.
    active_ids = {a.id for a in assets}
    # Chip expectations can use neutral imputation, but prediction ranges need
    # observed common history for every selected asset.
    common_ids = {
        sprint: set.intersection(*(set(s) for s in sample))
        for sprint, sample in samples.items()
    }
    imputed: set[str] = set()
    for sample in samples.values():
        for asset_id in sorted(active_ids):
            present = [s for s in sample if asset_id in s]
            if len(present) == len(sample):
                continue
            imputed.add(asset_id)
            if len(imputed) > MAX_IMPUTED:
                raise DataError(
                    "Chip history lacks a common sample for all active assets"
                )
            mean_s = [
                sum(components(s[asset_id])[k] for s in present) / len(present)
                if present
                else 0.0
                for k in range(3)
            ]
            for s in sample:
                if asset_id not in s:
                    s[asset_id] = Estimate(*mean_s)
    nn: dict[tuple[int, str], Estimate] = {}
    ap: dict[int, tuple[dict[str, Estimate], ...]] = {}
    joint = {}
    for t, weekend in enumerate(weekends):
        sample = samples[weekend.sprint]
        means = {}
        for asset in assets:
            forecast = estimates.get((t, asset.id))
            if forecast is None or not valid_estimate(forecast):
                raise DataError(f"Missing finite chip forecast for {asset.name}")
            means[asset.id] = tuple(
                sum(components(s[asset.id])[k] for s in sample) / len(sample)
                for k in range(3)
            )
            nn[t, asset.id] = no_negative_uplift(forecast)
        ap[t] = tuple(
            {
                a.id: Estimate(
                    *(
                        components(estimates[t, a.id])[k]
                        + components(scores[a.id])[k]
                        - means[a.id][k]
                        for k in range(3)
                    )
                )
                for a in assets
                if a.kind == "DRIVER"
            }
            for scores in sample
        )
        # Keep each historical weekend intact across every driver, constructor
        # and session. Independent asset sampling would lose their covariance.
        joint[t] = tuple(
            {
                "scores": {
                    a.id: Estimate(
                        *(
                            components(estimates[t, a.id])[k]
                            + components(scores[a.id])[k]
                            - means[a.id][k]
                            for k in range(3)
                        )
                    )
                    for a in assets
                    if a.id in common_ids[weekend.sprint]
                },
                "no_negative": {
                    a.id: Estimate(
                        *(
                            max(
                                0.0,
                                components(estimates[t, a.id])[k]
                                + components(scores[a.id])[k]
                                - means[a.id][k],
                            )
                            for k in range(3)
                        )
                    )
                    for a in assets
                    if a.id in common_ids[weekend.sprint]
                },
            }
            for scores in sample
        )
    return ChipValues(
        nn,
        ap,
        {t: tuple(sampled[w.sprint]) for t, w in enumerate(weekends)},
        tuple(sorted(skipped)),
        tuple(sorted(imputed)),
        joint,
    )


@dataclass(frozen=True)
class FinalFix:
    original: Lineup
    outgoing: Asset | None
    incoming: Asset | None
    drivers: tuple[Asset, ...]
    constructors: tuple[Asset, ...]
    boost: Asset
    cost: int
    accrued_points: float
    remaining_points: Estimate

    @property
    def expected_points(self) -> float:
        return self.accrued_points + self.remaining_points.total


def final_fix(
    lineup: Lineup,
    assets: tuple[Asset, ...],
    remaining: dict[str, Estimate],
    budget: int,
    *,
    available: bool,
    eligible: bool,
    accrued_points: float,
) -> FinalFix:
    """Choose zero or one same-kind replacement using ONLY supplied future points.

    Caller verifies the actual Final Fix window and supplies session-truncated
    estimates and already multiplier-adjusted accrued points. Boost follows its
    replaced driver. Original lineup and accrued points are retained verbatim.
    """
    if not available or not eligible or lineup.chip is not None:
        raise DataError(
            "Final Fix is unavailable, ineligible or another chip is active"
        )
    if budget < 0 or not isfinite(accrued_points):
        raise DataError("Invalid Final Fix budget or accrued points")
    known = {a.id: a for a in assets}
    original = lineup.drivers + lineup.constructors
    if (
        len(known) != len(assets)
        or len({a.id for a in original}) != 7
        or len(lineup.drivers) != 5
        or len(lineup.constructors) != 2
        or any(a.kind != "DRIVER" for a in lineup.drivers)
        or any(a.kind != "CONSTRUCTOR" for a in lineup.constructors)
        or lineup.boost not in lineup.drivers
        or lineup.x3 is not None
        or any(a.id not in known or known[a.id].kind != a.kind for a in original)
    ):
        raise DataError("Invalid Final Fix original team or active roster")
    for a in assets:
        if a.id not in remaining or not valid_estimate(remaining[a.id]):
            raise DataError(f"Missing finite remaining estimate for {a.name}")
    best = None
    selected = {a.id for a in original}
    candidates = [(None, None)] + [
        (old, new)
        for old in original
        for new in assets
        if new.id not in selected and new.kind == old.kind
    ]
    for old, new in candidates:
        team = tuple(known[a.id] if a != old else new for a in original)
        cost = sum(a.price for a in team)
        if cost > budget:
            continue
        boost = new if old == lineup.boost else known[lineup.boost.id]
        points = Estimate(
            *(
                sum(components(remaining[a.id])[k] for a in team)
                + components(remaining[boost.id])[k]
                for k in range(3)
            )
        )
        candidate = FinalFix(
            lineup,
            old,
            new,
            tuple(a for a in team if a.kind == "DRIVER"),
            tuple(a for a in team if a.kind == "CONSTRUCTOR"),
            boost,
            cost,
            accrued_points,
            points,
        )
        if best is None or points.total > best.remaining_points.total:
            best = candidate
    if best is None:
        raise DataError("No legal Final Fix team within budget")
    return best
