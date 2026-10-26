"""Point-in-time ranking diagnostics independent of post-race prices."""

from __future__ import annotations

from math import isfinite

from scipy.stats import spearmanr


def selection_metrics(assets: tuple) -> dict:
    """Compare unbudgeted picks; never present these as legal-team regret."""
    result = {}
    for kind, number, label in (
        ("DRIVER", 5, "drivers"),
        ("CONSTRUCTOR", 2, "constructors"),
    ):
        group = [item for item in assets if item.kind == kind]
        if len(group) < number + 1:
            result[label] = None
            continue
        predicted = sorted(group, key=lambda x: (-x.predicted.total, x.id))[:number]
        hindsight = sorted(group, key=lambda x: (-x.actual.total, x.id))[:number]
        p = [item.predicted.total for item in group]
        a = [item.actual.total for item in group]
        corr = (
            float(spearmanr(p, a).statistic)
            if max(p) != min(p) and max(a) != min(a)
            else None
        )
        result[label] = {
            "spearman_rank_correlation": corr
            if corr is not None and isfinite(corr)
            else None,
            "top_pick_overlap": len(
                {item.id for item in predicted} & {item.id for item in hindsight}
            ),
            "unbudgeted_points_regret": max(
                0.0,
                sum(item.actual.total for item in hindsight)
                - sum(item.actual.total for item in predicted),
            ),
            "number_selected": number,
        }
        if kind == "DRIVER":
            chosen_boost = max(predicted, key=lambda item: item.predicted.total)
            result[label]["boost_regret_within_predicted_five"] = max(
                0.0,
                max(item.actual.total for item in predicted)
                - chosen_boost.actual.total,
            )
    return result
