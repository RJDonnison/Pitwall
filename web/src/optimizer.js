// Same binary model as the Python optimizer: full seven-player lineups, durable
// Limitless restoration, once-per-season chips, exact net transfers and carry.
export const CHIPS = [
  "autopilot",
  "x3",
  "no_negative",
  "wildcard",
  "limitless",
  "final_fix",
];
export const PREWEEK = CHIPS.filter((name) => name !== "final_fix");
export const total = (sessions) =>
  sessions.reduce((sum, value) => sum + value, 0);
const fail = (message) => {
  throw new Error(message);
};

export function validateDataset(data, now = Date.now()) {
  if (data?.schema_version !== 1 || data.status !== "ready")
    fail(
      data?.message ||
        "Forecasts are unavailable. Refresh the published data first.",
    );
  const generated = Date.parse(data.generated_at);
  if (
    !Number.isFinite(generated) ||
    generated > now + 300000 ||
    now - generated > 6 * 3600000
  )
    fail(
      "The published forecasts are more than six hours old. Wait for the next data refresh.",
    );
  if (
    !Array.isArray(data.assets) ||
    new Set(data.assets.map((a) => a.id)).size !== data.assets.length ||
    data.assets.some(
      (a) =>
        typeof a.id !== "string" ||
        !["DRIVER", "CONSTRUCTOR"].includes(a.kind) ||
        !Number.isInteger(a.price_tenths_m) ||
        a.price_tenths_m <= 0,
    )
  )
    fail("Cannot verify the published roster and prices.");
  if (
    data.assets.filter((a) => a.kind === "DRIVER").length < 5 ||
    data.assets.filter((a) => a.kind === "CONSTRUCTOR").length < 2
  )
    fail("The roster cannot form a full team.");
  if (!Array.isArray(data.rounds) || !data.rounds.length)
    fail("There are no published upcoming rounds.");
  let previous = -Infinity;
  for (const round of data.rounds) {
    const start = Date.parse(round.first_session_utc);
    if (
      !Number.isFinite(start) ||
      start <= now ||
      start <= previous ||
      round.season !== data.season ||
      round.locked
    )
      fail(
        "The published round is started, locked or inconsistent. Refresh the forecasts.",
      );
    previous = start;
    for (const a of data.assets) {
      const score = round.forecasts?.[a.id];
      if (
        !Array.isArray(score) ||
        score.length !== 3 ||
        score.some((v) => !Number.isFinite(v))
      )
        fail(`Missing forecast for ${a.name}.`);
      if (!round.sprint && score[1] !== 0)
        fail("A regular weekend contains Sprint points.");
    }
  }
  return data;
}

export function validateTeam(data, team) {
  const selected = new Set(team.selected);
  const roster = new Map(data.assets.map((a) => [a.id, a]));
  const validSeven = (ids) =>
    ids.length === 7 &&
    new Set(ids).size === 7 &&
    ids.every((id) => roster.has(id)) &&
    ids.filter((id) => roster.get(id).kind === "DRIVER").length === 5;
  if (!validSeven(team.selected))
    fail("Choose exactly five drivers and two constructors.");
  if (
    !Number.isInteger(team.budget) ||
    team.budget <= 0 ||
    ![0, 1].includes(team.carry)
  )
    fail(
      "Enter a positive budget in $0.1m increments and zero or one carried transfer.",
    );
  if (
    !Array.isArray(team.chips) ||
    new Set(team.chips).size !== team.chips.length ||
    team.chips.some((c) => !CHIPS.includes(c))
  )
    fail("Invalid remaining chip inventory.");
  if (team.active && !PREWEEK.includes(team.active))
    fail(
      "An active Final Fix needs remaining-session planning, not a pre-weekend season plan.",
    );
  if (team.active === "limitless" && !validSeven(team.restore || []))
    fail(
      "Choose the five drivers and two constructors that Limitless will restore.",
    );
  if (team.initial && (team.carry || team.active === "limitless"))
    fail(
      "An initial team cannot carry transfers or restore a Limitless roster.",
    );
  if (
    team.active !== "limitless" &&
    data.assets
      .filter((a) => selected.has(a.id))
      .reduce((s, a) => s + a.price_tenths_m, 0) > team.budget
  )
    fail("Your starting roster exceeds the entered total budget.");
  return team;
}

function chipInputs(data, allowed) {
  data.rounds.forEach((round, t) => {
    if (allowed[t].includes("no_negative"))
      for (const a of data.assets) {
        const delta = round.no_negative?.[a.id];
        if (
          !Array.isArray(delta) ||
          delta.length !== 3 ||
          delta.some((v) => !Number.isFinite(v) || v < 0)
        )
          fail(`No verified No Negative uplift for ${a.name}.`);
      }
    if (allowed[t].includes("autopilot")) {
      if (!round.autopilot?.length)
        fail("No common Autopilot scenarios are available.");
      for (const a of data.assets.filter((a) => a.kind === "DRIVER"))
        for (let k = 0; k < 3; k++) {
          const samples = round.autopilot.map((s) => s[a.id]?.[k]);
          if (
            samples.some((v) => !Number.isFinite(v)) ||
            Math.abs(
              total(samples) / samples.length - round.forecasts[a.id][k],
            ) > 1e-6
          )
            fail("Autopilot scenarios do not match the forecasts.");
        }
    }
  });
}

export function buildModel(data, team) {
  validateTeam(data, team);
  const { assets, rounds } = data;
  const drivers = assets.filter((a) => a.kind === "DRIVER");
  const constructors = assets.filter((a) => a.kind === "CONSTRUCTOR");
  const allowed = rounds.map((r, t) =>
    t === 0 && team.active
      ? [team.active]
      : team.chips.filter(
          (c) =>
            PREWEEK.includes(c) &&
            (!team.active || c !== team.active) &&
            (!["wildcard", "limitless"].includes(c) ||
              (r.round > 1 && (t > 0 || team.completed))) &&
            (c !== "limitless" || t > 0 || !team.initial),
        ),
  );
  chipInputs(data, allowed);
  const objective = [],
    upper = [],
    rows = [];
  const variable = (cost = 0, bound = 1) => {
    const i = objective.length;
    objective.push(cost);
    upper.push(bound);
    return i;
  };
  const row = (terms, low = -Infinity, high = Infinity) =>
    rows.push({ terms: new Map(terms), low, high });
  const both = (l, r, cost) => {
    const j = variable(cost);
    row(
      [
        [j, 1],
        [l, -1],
      ],
      -Infinity,
      0,
    );
    row(
      [
        [j, 1],
        [r, -1],
      ],
      -Infinity,
      0,
    );
    row(
      [
        [j, 1],
        [l, -1],
        [r, -1],
      ],
      -1,
    );
  };
  const selected = [],
    boosted = [],
    durable = [],
    incoming = [],
    extra = [],
    carried = [],
    chips = [],
    tripled = [];
  for (let t = 0; t < rounds.length; t++) {
    const round = rounds[t];
    const h = Object.fromEntries(allowed[t].map((c) => [c, variable()]));
    chips.push(h);
    row(
      Object.values(h).map((v) => [v, 1]),
      -Infinity,
      1,
    );
    if (t === 0 && team.active) row([[h[team.active], 1]], 1, 1);
    const x = {},
      b = {},
      z = {},
      persistent = {},
      triple = {};
    for (const a of assets) {
      const score = total(round.forecasts[a.id]);
      x[a.id] = variable(-score);
      if (a.kind === "DRIVER") {
        b[a.id] = variable(-score);
        row(
          [
            [b[a.id], 1],
            [x[a.id], -1],
          ],
          -Infinity,
          0,
        );
        if ("autopilot" in h) both(b[a.id], h.autopilot, score);
        if ("x3" in h) {
          triple[a.id] = variable(-2 * score);
          row(
            [
              [triple[a.id], 1],
              [x[a.id], -1],
            ],
            -Infinity,
            0,
          );
          row(
            [
              [triple[a.id], 1],
              [b[a.id], 1],
            ],
            -Infinity,
            1,
          );
        }
      }
      if ("no_negative" in h) {
        const uplift = total(round.no_negative[a.id]);
        both(x[a.id], h.no_negative, -uplift);
        if (a.kind === "DRIVER") both(b[a.id], h.no_negative, -uplift);
      }
      persistent[a.id] = variable();
      if (!("limitless" in h))
        row(
          [
            [persistent[a.id], 1],
            [x[a.id], -1],
          ],
          0,
          0,
        );
      else {
        row(
          [
            [persistent[a.id], 1],
            [x[a.id], -1],
            [h.limitless, -1],
          ],
          -Infinity,
          0,
        );
        row(
          [
            [persistent[a.id], -1],
            [x[a.id], 1],
            [h.limitless, -1],
          ],
          -Infinity,
          0,
        );
        if (t) {
          const prior = durable[t - 1][a.id];
          row(
            [
              [persistent[a.id], 1],
              [prior, -1],
              [h.limitless, 1],
            ],
            -Infinity,
            1,
          );
          row(
            [
              [persistent[a.id], -1],
              [prior, 1],
              [h.limitless, 1],
            ],
            -Infinity,
            1,
          );
        } else {
          const prior = (team.active === "limitless"
            ? team.restore
            : team.selected
          ).includes(a.id)
            ? 1
            : 0;
          row(
            [
              [persistent[a.id], 1],
              [h.limitless, 1],
            ],
            -Infinity,
            1 + prior,
          );
          row(
            [
              [persistent[a.id], -1],
              [h.limitless, 1],
            ],
            -Infinity,
            1 - prior,
          );
        }
      }
    }
    row(
      drivers.map((a) => [x[a.id], 1]),
      5,
      5,
    );
    row(
      constructors.map((a) => [x[a.id], 1]),
      2,
      2,
    );
    const prices = assets.map((a) => [x[a.id], a.price_tenths_m]);
    if ("limitless" in h)
      prices.push([
        h.limitless,
        -Math.max(0, total(assets.map((a) => a.price_tenths_m)) - team.budget),
      ]);
    row(prices, -Infinity, team.budget);
    row(
      Object.values(b).map((i) => [i, 1]),
      1,
      1,
    );
    if (Object.keys(triple).length)
      row([...Object.values(triple).map((i) => [i, 1]), [h.x3, -1]], 0, 0);
    if ("autopilot" in h)
      for (const scenario of round.autopilot) {
        const winners = drivers.map((a) => {
          const w = variable(-total(scenario[a.id]) / round.autopilot.length);
          row(
            [
              [w, 1],
              [x[a.id], -1],
            ],
            -Infinity,
            0,
          );
          return [w, 1];
        });
        row([...winners, [h.autopilot, -1]], 0, 0);
      }
    selected.push(x);
    boosted.push(b);
    durable.push(persistent);
    tripled.push(triple);
    if (t === 0 && team.initial) {
      incoming.push(z);
      extra.push(null);
      carried.push(null);
      continue;
    }
    for (const a of assets) {
      const prior = t
        ? durable[t - 1][a.id]
        : Number(team.selected.includes(a.id));
      z[a.id] = variable();
      row(
        [[z[a.id], 1], [x[a.id], -1], ...(t ? [[prior, 1]] : [])],
        t ? 0 : -prior,
      );
      row(
        [
          [z[a.id], 1],
          [x[a.id], -1],
        ],
        -Infinity,
        0,
      );
      row(
        [[z[a.id], 1], ...(t ? [[prior, 1]] : [])],
        -Infinity,
        t ? 1 : 1 - prior,
      );
    }
    incoming.push(z);
    const penalty = variable(10, team.allowPenalties ? 7 : 0);
    extra.push(penalty);
    const available = t ? carried[t - 1] : null;
    const nextCarry = t < rounds.length - 1 ? variable() : null;
    carried.push(nextCarry);
    const allowance = 2 + (t === 0 ? team.carry : 0);
    const coefficients = [
      ...Object.values(z).map((i) => [i, 1]),
      [penalty, -1],
    ];
    if (available !== null) coefficients.push([available, -1]);
    if (nextCarry !== null) {
      coefficients.push([nextCarry, 1]);
      row(
        [
          [nextCarry, 7],
          [penalty, 1],
        ],
        -Infinity,
        7,
      );
      if ("limitless" in h)
        row(
          [
            [nextCarry, 1],
            [h.limitless, 1],
          ],
          -Infinity,
          1,
        );
      row(
        [
          ...Object.values(z).map((i) => [i, 1]),
          [nextCarry, 7],
          ...(available !== null ? [[available, -1]] : []),
        ],
        -Infinity,
        allowance + 6,
      );
    }
    for (const name of ["wildcard", "limitless"])
      if (name in h) coefficients.push([h[name], -8]);
    if (team.limitlessFollowup === true && t && "limitless" in chips[t - 1])
      coefficients.push([chips[t - 1].limitless, -8]);
    row(coefficients, -Infinity, allowance);
  }
  for (const name of PREWEEK)
    row(
      chips.filter((h) => name in h).map((h) => [h[name], 1]),
      -Infinity,
      1,
    );
  const terms = (pairs) =>
    [...pairs]
      .filter(([, v]) => v !== 0)
      .map(([i, v]) => `${v < 0 ? "-" : "+"} ${Math.abs(v)} v${i}`)
      .join(" ") || "+ 0 v0";
  const constraints = rows.flatMap((r, i) =>
    r.low === r.high
      ? [` c${i}: ${terms(r.terms)} = ${r.low}`]
      : [
          ...(Number.isFinite(r.low)
            ? [` l${i}: ${terms(r.terms)} >= ${r.low}`]
            : []),
          ...(Number.isFinite(r.high)
            ? [` u${i}: ${terms(r.terms)} <= ${r.high}`]
            : []),
        ],
  );
  const lp = [
    "Minimize",
    ` obj: ${terms(objective.map((v, i) => [i, v]))}`,
    "Subject To",
    ...constraints,
    "Bounds",
    ...upper.map((u, i) => ` 0 <= v${i} <= ${u}`),
    "Generals",
    ...upper.map((_, i) => ` v${i}`),
    "End",
  ].join("\n");
  return { lp, selected, boosted, incoming, extra, carried, chips, tripled };
}

export function optimize(highs, data, team) {
  const model = buildModel(data, team);
  const solved = highs.solve(model.lp, {
    output_flag: false,
    time_limit: 90,
    mip_rel_gap: 0,
    mip_abs_gap: 0,
  });
  if (solved.Status !== "Optimal")
    fail(
      `No proven optimal plan (${solved.Status}). Try disabling an optional chip or retry on a faster device.`,
    );
  const value = (i) => (i == null ? 0 : (solved.Columns[`v${i}`]?.Primal ?? 0));
  let prior = [...team.selected];
  const rounds = data.rounds.map((r, t) => {
    const chosen = data.assets.filter(
      (a) => value(model.selected[t][a.id]) > 0.5,
    );
    const boost = chosen.find((a) => value(model.boosted[t][a.id]) > 0.5);
    const x3 = chosen.find((a) => value(model.tripled[t][a.id]) > 0.5);
    const chip =
      Object.keys(model.chips[t]).find((c) => value(model.chips[t][c]) > 0.5) ||
      null;
    const entries = chosen.map((a) => {
      const base = [...r.forecasts[a.id]],
        extra = [0, 0, 0];
      if (chip === "autopilot" && a.kind === "DRIVER")
        for (const scenario of r.autopilot) {
          const best = chosen
            .filter((b) => b.kind === "DRIVER")
            .reduce((l, b) =>
              total(scenario[b.id]) > total(scenario[l.id]) ? b : l,
            );
          if (best.id === a.id)
            for (let k = 0; k < 3; k++)
              extra[k] += scenario[a.id][k] / r.autopilot.length;
        }
      if (chip !== "autopilot" && a.id === boost.id)
        for (let k = 0; k < 3; k++) extra[k] += base[k];
      if (a.id === x3?.id) for (let k = 0; k < 3; k++) extra[k] += 2 * base[k];
      if (chip === "no_negative")
        for (let k = 0; k < 3; k++)
          extra[k] += r.no_negative[a.id][k] * (a.id === boost.id ? 2 : 1);
      return {
        id: a.id,
        base,
        extra,
        sessions: base.map((v, k) => v + extra[k]),
        points: total(base) + total(extra),
      };
    });
    const ids = chosen.map((a) => a.id);
    const penalty = 10 * Math.round(value(model.extra[t]));
    const result = {
      ...r,
      entries,
      boost: boost.id,
      x3: x3?.id || null,
      chip,
      cost: total(chosen.map((a) => a.price_tenths_m)),
      penalty,
      transfers: Math.round(total(Object.values(model.incoming[t]).map(value))),
      carry: Math.round(value(model.carried[t])),
      in:
        team.initial && t === 0 ? [] : ids.filter((id) => !prior.includes(id)),
      out:
        team.initial && t === 0 ? [] : prior.filter((id) => !ids.includes(id)),
      sessions: [0, 1, 2].map((k) => total(entries.map((e) => e.sessions[k]))),
      points: total(entries.map((e) => e.points)) - penalty,
    };
    if (chip !== "limitless") prior = ids;
    else if (t === 0)
      prior =
        team.active === "limitless" ? [...team.restore] : [...team.selected];
    return result;
  });
  const points = total(rounds.map((r) => r.points));
  if (Math.abs(points + solved.ObjectiveValue) > 1e-4)
    fail("Solver result did not pass the independent points check.");
  return { rounds, points, status: "Optimal" };
}
