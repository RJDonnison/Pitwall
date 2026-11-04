"""Plackett-Luce race simulation with team structure (opt-in alternative model).

The shipped rank model (``predict_model._draw``) averages finishing *ranks* and
adds Gaussian noise of a fixed size. Ranks discard margin (a car that is always
second by a second and a car that is always second by a tenth look the same),
which flattens win probabilities, and per-driver noise leaves teammates
independent of each other.

This module keeps the same inputs (completed sessions before the cutoff, with
the recency and regulation-era weights of ``history_weights``) but:

* fits driver strengths as a regularised Plackett-Luce model, where a driver's
  strength is a team (car) term plus a smaller driver term. Consistent winners
  earn large strengths, so dominance is represented;
* simulates finishing orders exactly from those strengths (Gumbel noise), with
  optional shocks shared by a team's two cars within a weekend;
* pools retirement risk by team (reliability is mostly a car property) with
  recency weights, instead of a per-driver rate;
* returns the same structure as ``predict_model._draw`` so it can be selected
  with ``_draw(..., model="plackett")``.

Only sessions before the forecast cutoff are used, exactly like the rank model.
The telemetry circuit adjustment of the rank model is not applied here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import minimize

from . import history_weights

QUALIFYING_KINDS = frozenset({"Q", "SQ"})
# Sessions with little history borrow strength from the full session of the
# same family, at a reduced weight.
BORROW = {"S": "R", "SQ": "Q"}

_ALIASES = {
    "kicksauber": "audi",
    "stakef1teamkicksauber": "audi",
    "alfaromeo": "audi",
    "visacashapprb": "racingbulls",
    "rb": "racingbulls",
    "alphatauri": "racingbulls",
    "oracleredbullracing": "redbullracing",
    "tgrhaasf1team": "haas",
    "haasf1team": "haas",
    "mclarenf1team": "mclaren",
    "scuderiaferrari": "ferrari",
    "astonmartinaramco": "astonmartin",
}

# Prior failure rate when a session type has no history at all.
_DEFAULT_FAILURE = {"R": 0.10, "S": 0.08, "Q": 0.02, "SQ": 0.02}


@dataclass(frozen=True)
class RaceModelConfig:
    """Tunable parameters. Defaults come from the walk-forward grids reported in
    the paired model comparison (``python -m f1fantasy.model_compare``)."""

    half_life: float = 3.0  # races, recency decay of the strength fit
    team_ridge: float = 0.3  # shrinks team strengths toward the field average
    driver_ridge: float = 1.5  # shrinks the driver-minus-team term toward zero
    scale: float = 1.0  # multiplies strengths; >1 sharpens, <1 flattens
    team_shock: float = 0.0  # sd of a weekend shock shared by both cars
    driver_shock: float = 0.0  # sd of an extra per-driver weekend shock
    borrow_weight: float = 0.35  # weight of the full session for Sprint sessions
    quali_weight: float = 1.0  # weight of qualifying results as evidence for race pace
    grid_effect: bool = False  # condition the race on the known grid (post-qualifying)
    reliability_half_life: float = 12.0  # races
    reliability_team_prior: float = 8.0  # pseudo-entries at the field rate
    reliability_driver_prior: float = 16.0  # pseudo-entries at the team rate
    attrition_sd: float = 0.0  # sd (log scale) of a race-wide retirement factor

    @classmethod
    def post_qualifying(cls, **overrides):
        """Race forecast conditioned on the known starting grid.

        Pace terms are shrunk hard: in the walk-forward evaluation the grid
        carries almost all of the information, and weakly shrunk pace terms
        made podium forecasts worse.
        """
        values = dict(
            half_life=3.0,
            team_ridge=10.0,
            driver_ridge=20.0,
            scale=1.3,
            grid_effect=True,
        )
        values.update(overrides)
        return cls(**values)


def team_key(name) -> str:
    """Stable team identity across sponsor renames; unknown names stay distinct."""
    key = "".join(c for c in str(name).casefold() if c.isalnum())
    return _ALIASES.get(key, key)


def _ok(row, kind) -> bool:
    if kind in QUALIFYING_KINDS:
        return bool(row.get("qualified", True))
    return bool(row.get("classified"))


def _team_of(records, drivers):
    """Current team of each target driver: latest row, else a teammate's."""
    latest = {}
    for record in records:  # chronological, later rows overwrite
        for kind in ("R", "Q", "S", "SQ"):
            for row in record["sessions"].get(kind, []):
                if row.get("team_name"):
                    latest[row["tla"]] = team_key(row["team_name"])
    by_team = {}
    for d in drivers:
        if d["tla"] in latest:
            by_team.setdefault(str(d["team_id"]), latest[d["tla"]])
    return {
        d["tla"]: latest.get(d["tla"], by_team.get(str(d["team_id"]))) for d in drivers
    }


def _grid_covariate(record, tla, n):
    """-log(qualifying position): the grid advantage of one driver in one race."""
    rows = record["sessions"].get("Q", [])
    position = next(
        (r["position"] for r in rows if r["tla"] == tla and r.get("position")), None
    )
    return -float(np.log(position if position else n))


def _sessions(records, kind, target_season, half_life, config):
    """Weighted, ordered sessions: [(weight, [(tla, team, covariate), ...] best first)]."""
    out = []
    sources = [(kind, 1.0)]
    if kind in BORROW:
        sources.append((BORROW[kind], config.borrow_weight))
    if kind == "R" and config.quali_weight > 0 and not config.grid_effect:
        sources.append(("Q", config.quali_weight))
    for source, multiplier in sources:
        used = [r for r in records if r["sessions"].get(source)]
        weights = history_weights.weights(
            [r["season"] for r in used], target_season, half_life
        )
        for record, weight in zip(used, weights):
            weight *= multiplier
            if weight < 1e-4:
                continue
            rows = [
                row
                for row in record["sessions"][source]
                if row.get("position") and _ok(row, source)
            ]
            rows.sort(key=lambda row: row["position"])
            if len(rows) >= 2:
                size = len(record["sessions"][source])
                covariate = config.grid_effect and kind == "R" and source == "R"
                out.append(
                    (
                        weight,
                        [
                            (
                                r["tla"],
                                team_key(r["team_name"]),
                                _grid_covariate(record, r["tla"], size)
                                if covariate
                                else 0.0,
                            )
                            for r in rows
                        ],
                    )
                )
    return out


def _problem(sessions, config):
    """Index maps and the penalised negative log-likelihood with its gradient."""
    tlas = sorted({t for _, rows in sessions for t, _, _ in rows})
    teams = sorted({m for _, rows in sessions for _, m, _ in rows})
    di = {t: i for i, t in enumerate(tlas)}
    ti = {m: i for i, m in enumerate(teams)}
    packed = [
        (
            w,
            np.array([di[t] for t, _, _ in rows]),
            np.array([ti[m] for _, m, _ in rows]),
            np.array([x for _, _, x in rows]),
        )
        for w, rows in sessions
    ]
    n_teams = len(teams)
    use_beta = config.grid_effect

    def objective(x):
        a, b = x[:n_teams], x[n_teams : n_teams + len(tlas)]
        beta = x[-1] if use_beta else 0.0
        total = 0.5 * config.team_ridge * (a @ a) + 0.5 * config.driver_ridge * (b @ b)
        ga = config.team_ridge * a
        gb = config.driver_ridge * b
        gbeta = 0.0
        for weight, d, t, cov in packed:
            theta = a[t] + b[d] + beta * cov
            lse = np.logaddexp.accumulate(theta[::-1])[::-1]
            total -= weight * np.sum(theta - lse)
            grad = 1.0 - np.exp(theta) * np.cumsum(np.exp(-lse))
            np.add.at(ga, t, -weight * grad)
            np.add.at(gb, d, -weight * grad)
            gbeta -= weight * float(grad @ cov)
        gradient = np.concatenate([ga, gb] + ([[gbeta]] if use_beta else []))
        return total, gradient

    return tlas, teams, objective


def fit_strengths(sessions, config):
    """Regularised weighted Plackett-Luce fit: theta = team + driver (+ beta * grid).

    Returns ``(team_terms, driver_terms, beta)``; ``beta`` is the fitted weight
    of the grid covariate (0 unless ``config.grid_effect``).
    """
    if not sessions:
        return {}, {}, 0.0
    tlas, teams, objective = _problem(sessions, config)
    n_teams = len(teams)
    start = np.zeros(n_teams + len(tlas) + (1 if config.grid_effect else 0))
    result = minimize(objective, start, jac=True, method="L-BFGS-B")
    a, b = result.x[:n_teams], result.x[n_teams : n_teams + len(tlas)]
    beta = float(result.x[-1]) if config.grid_effect else 0.0
    return dict(zip(teams, a)), dict(zip(tlas, b)), beta


def strengths(records, kind, drivers, team_of, season, config, grid=None):
    """Strength of each target driver for one session type.

    With ``config.grid_effect`` the race strength includes the fitted grid
    advantage; ``grid`` maps driver code to starting position and is required.
    """
    sessions = _sessions(records, kind, season, config.half_life, config)
    team_terms, driver_terms, beta = fit_strengths(sessions, config)
    theta = np.array(
        [
            team_terms.get(team_of.get(d["tla"]), 0.0) + driver_terms.get(d["tla"], 0.0)
            for d in drivers
        ]
    )
    if config.grid_effect and kind == "R":
        if grid is None:
            raise ValueError("grid_effect requires the starting grid")
        worst = max(len(drivers), max(grid.values()))
        theta = theta + beta * np.array(
            [-np.log(grid.get(d["tla"], worst)) for d in drivers]
        )
    return theta


def failure_rates(records, kind, drivers, team_of, season, config):
    """Probability of not being classified/qualified, pooled by team.

    driver = (driver failures + m_d * team rate) / (driver entries + m_d), and
    the team rate is itself shrunk toward the field rate. All counts carry
    recency and regulation-era weights.
    """
    used = [r for r in records if r["sessions"].get(kind)]
    weights = history_weights.weights(
        [r["season"] for r in used], season, config.reliability_half_life
    )
    driver_n, driver_f, team_n, team_f = {}, {}, {}, {}
    field_n = field_f = 0.0
    for record, weight in zip(used, weights):
        for row in record["sessions"][kind]:
            failed = 0.0 if _ok(row, kind) else 1.0
            tla, team = row["tla"], team_key(row.get("team_name", ""))
            driver_n[tla] = driver_n.get(tla, 0.0) + weight
            driver_f[tla] = driver_f.get(tla, 0.0) + weight * failed
            team_n[team] = team_n.get(team, 0.0) + weight
            team_f[team] = team_f.get(team, 0.0) + weight * failed
            field_n += weight
            field_f += weight * failed
    default = _DEFAULT_FAILURE.get(kind, 0.1)
    field = (field_f + 2.0 * default) / (field_n + 2.0)
    rates = []
    for d in drivers:
        team = team_of.get(d["tla"])
        t_n, t_f = team_n.get(team, 0.0), team_f.get(team, 0.0)
        team_rate = (t_f + config.reliability_team_prior * field) / (
            t_n + config.reliability_team_prior
        )
        n, f = driver_n.get(d["tla"], 0.0), driver_f.get(d["tla"], 0.0)
        rates.append(
            (f + config.reliability_driver_prior * team_rate)
            / (n + config.reliability_driver_prior)
        )
    return np.array(rates)


def _fastest_lap(records, key, tlas, ranks, classified, rng):
    """Same rule as the rank model: in-season fastest laps plus a rank term."""
    lap_history = [r for r in records if r.get(key)][-8:]
    counts = np.array([sum(r.get(key) == tla for r in lap_history) for tla in tlas])
    weights = (counts[None, :] + 2 / np.maximum(ranks, 1)) * classified
    weights[weights.sum(axis=1) == 0] = 1
    cumulative = np.cumsum(weights / weights.sum(axis=1)[:, None], axis=1)
    return (cumulative < rng.random((len(ranks), 1))).sum(axis=1)


def draw(
    records,
    drivers,
    simulations,
    rng,
    telemetry=None,
    season=None,
    half_life=None,
    config=None,
    kinds=None,
    grid=None,
):
    """Drop-in alternative to ``predict_model._draw`` (telemetry is not used)."""
    config = config or RaceModelConfig()
    if half_life is not None:
        config = replace(config, half_life=half_life)
    n = len(drivers)
    tlas = [d["tla"] for d in drivers]
    season = int(season) if season is not None else int(records[-1]["season"])
    team_of = _team_of(records, drivers)
    teams = sorted({str(team_of.get(t)) for t in tlas})
    team_index = np.array([teams.index(str(team_of.get(t))) for t in tlas])
    # Weekend shocks are drawn once and shared by every session of the weekend,
    # which keeps qualifying and race outcomes correlated.
    shock = rng.normal(0.0, config.team_shock, (simulations, len(teams)))[
        :, team_index
    ] + rng.normal(0.0, config.driver_shock, (simulations, n))
    attrition = np.ones((simulations, 1))
    if config.attrition_sd > 0:
        sd = config.attrition_sd
        attrition = np.exp(rng.normal(-0.5 * sd * sd, sd, (simulations, 1)))
    available = {
        k for k in ("Q", "R", "S", "SQ") if any(r["sessions"].get(k) for r in records)
    }
    wanted = kinds or ["Q", "R", "S"] + (["SQ"] if "SQ" in available else [])
    output = {}
    for kind in wanted:
        theta = strengths(records, kind, drivers, team_of, season, config, grid)
        performance = config.scale * theta + shock + rng.gumbel(size=(simulations, n))
        rates = failure_rates(records, kind, drivers, team_of, season, config)
        failed = rng.random((simulations, n)) < np.minimum(rates * attrition, 0.95)
        classified = ~failed
        key = np.where(classified, performance, -1e6 - rng.random((simulations, n)))
        order = np.argsort(-key, axis=1, kind="stable")
        ranks = np.empty_like(order)
        np.put_along_axis(ranks, order, np.arange(1, n + 1)[None, :], axis=1)
        output[kind] = {"ranks": ranks, "classified": classified}
    for kind, key in (("R", "fastest_lap"), ("S", "sprint_fastest_lap")):
        if kind not in output:
            continue
        if kind == "S" and not any(r.get(key) for r in records):
            continue
        output[key] = _fastest_lap(
            records, key, tlas, output[kind]["ranks"], output[kind]["classified"], rng
        )
    return output
