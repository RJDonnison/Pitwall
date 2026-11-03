import {
  esc,
  points,
  teamColor,
  helmet,
  car,
  constructorName,
} from "./views.js";
import { portrait } from "./visuals.js";

const pct = (p) =>
  Number.isFinite(p) ? `${(100 * p).toFixed(1)}%` : "Unavailable";
const image = (a) => portrait(a, a.kind === "DRIVER" ? helmet() : car());

const position = (value) =>
  Number.isFinite(value) ? `P${points(value)}` : "Unavailable";

// The most likely *finish*. "Not classified" is one bucket that gathers every
// retirement, so it can out-weigh each single position without being the most likely
// way to finish; it is reported separately rather than competing with positions.
function mostLikelyResult(p) {
  if (!p) return { label: "Unavailable", probability: null, tied: false };
  const peak = Math.max(...p.positions);
  if (!(peak > 0)) return { label: "NC", probability: p.nc, tied: false };
  const modes = p.positions.flatMap((value, i) =>
    Math.abs(value - peak) < 1e-9 ? [`P${i + 1}`] : [],
  );
  return {
    label:
      modes.length <= 2 ? modes.join(" / ") : `${modes.length} tied outcomes`,
    probability: peak,
    tied: modes.length > 1,
  };
}

function curve(asset, p, label) {
  const n = p.positions.length;
  // One absolute scale for positions and NC, so every height is the true chance.
  const scale = Math.max(0.01, ...p.positions, p.nc);
  const y = (v) => 126 - (98 * v) / scale;
  const coords = p.positions.map((v, i) => [
    48 + (i * 368) / Math.max(1, n - 1),
    y(v),
  ]);
  const secants = coords
    .slice(1)
    .map(([x, yy], i) => (yy - coords[i][1]) / (x - coords[i][0]));
  // Monotone cubic interpolation preserves every probability, without bumps
  // beyond neighbouring observations or a flat tangent at every single point.
  const slopes = coords.map((_, i) => {
    if (!i) return secants[0] || 0;
    if (i === coords.length - 1) return secants[i - 1] || 0;
    const a = secants[i - 1],
      b = secants[i];
    return a * b > 0 ? (2 * a * b) / (a + b) : 0;
  });
  const line = coords
    .map(([x, yy], i) => {
      if (!i) return `M${x},${yy}`;
      const [px, py] = coords[i - 1],
        dx = (x - px) / 3;
      return `C${px + dx},${py + dx * slopes[i - 1]} ${x - dx},${yy - dx * slopes[i]} ${x},${yy}`;
    })
    .join(" ");
  const ticks = [...new Set([0, Math.floor((n - 1) / 2), n - 1])];
  const axis = [0, 0.5, 1]
    .map(
      (f) =>
        `<text class="curve-axis" x="40" y="${126 - 98 * f + 3}" text-anchor="end">${Math.round(scale * f * 100)}%</text>`,
    )
    .join("");
  return `<svg class="placement-curve" viewBox="0 0 440 160" role="group" aria-label="${esc(asset.name)} ${label} finishing position probabilities"><path class="curve-grid" d="M48 28H416 M48 77H416 M48 126H416"/>${axis}<path class="curve-area" d="${line} L${coords[n - 1][0]},126 L48,126Z"/><path class="curve-line" d="${line}"/>${coords
    .map(([x, yy], i) => {
      const text = `P${i + 1} · ${pct(p.positions[i])}`;
      return `<g class="curve-point" tabindex="0" role="img" aria-label="${text}"><circle class="curve-hit" cx="${x}" cy="${yy}" r="8"/><circle cx="${x}" cy="${yy}" r="2"/><g class="curve-tooltip" transform="translate(${Math.min(330, Math.max(0, x - 40))},${Math.max(0, yy - 28)})"><rect width="80" height="20" rx="3"/><text x="40" y="14" text-anchor="middle">${text}</text></g></g>`;
    })
    .join(
      "",
    )}${ticks.map((i) => `<text x="${coords[i][0]}" y="150" text-anchor="middle">P${i + 1}</text>`).join("")}</svg>`;
}

function placements(asset, data, sprint, named) {
  return `<article class="placement-card">${named ? `<div class="detail-identity">${image(asset)}<h3>${esc(asset.name)}</h3></div>` : ""}${[
    "Q",
    ...(sprint ? ["S"] : []),
    "R",
  ]
    .map((kind) => {
      const p = data?.[kind],
        label = { Q: "Qualifying", S: "Sprint", R: "Race" }[kind];
      if (!p) return `<p>${label}: placement estimates unavailable.</p>`;
      const likely = mostLikelyResult(p);
      return `<section class="placement-session"><h4>${label}</h4><dl class="placement-stats"><div><dt>Most likely</dt><dd>${likely.label}<small>${pct(likely.probability)}${likely.tied ? " each" : ""}</small></dd></div><div><dt>Expected</dt><dd>${position(p.mean)}</dd></div><div><dt>Not classified</dt><dd>${pct(p.nc)}</dd></div></dl>${curve(asset, p, label)}</section>`;
    })
    .join("")}</article>`;
}

function championshipStats(row) {
  return [
    [
      "Post-race championship",
      row ? `${points(row.points)} pts` : "Unavailable",
    ],
    ["Expected championship position", position(row?.standing_mean)],
    ["Weekend points", row ? `+${points(row.round_points)}` : "Unavailable"],
  ];
}

const forecastTotal = (round, a) =>
  (round.forecasts?.[a.id] || []).reduce((t, v) => t + v, 0);

function tile(dataset, probabilities, a, asset, byTeam) {
  const likely = mostLikelyResult(probabilities?.placements?.[a.id]?.R);
  return `<button type="button" class="participant-tile market-card ${a.id === asset.id ? "selected" : ""}" id="insight-participant-${esc(a.id)}" data-insight-entity="${esc(a.id)}" aria-pressed="${a.id === asset.id}" style="--team-color:${teamColor(dataset, a)}"><span class="market-card-title"><span class="registry-photo">${image(a)}</span><span class="participant-tile-name"><strong>${esc(a.name)}</strong>${a.kind === "DRIVER" && !byTeam ? `<small>${esc(constructorName(dataset, a))}</small>` : ""}</span></span><span class="market-card-bottom">${a.kind === "DRIVER" ? `<span class="participant-position"><small>Likely race</small><strong>${likely.label}</strong></span>` : ""}</span></button>`;
}

// Drivers are grouped by team (strongest forecast first) so teammates sit together;
// teams are a plain ranked grid.
function participantTiles(
  dataset,
  round,
  probabilities,
  population,
  assets,
  asset,
) {
  const ranked = [...assets].sort(
    (a, b) =>
      forecastTotal(round, b) - forecastTotal(round, a) ||
      a.name.localeCompare(b.name),
  );
  if (population !== "drivers")
    return ranked
      .map((a) => tile(dataset, probabilities, a, asset, false))
      .join("");
  const teams = new Map();
  for (const a of ranked) {
    if (!teams.has(a.team_id)) teams.set(a.team_id, []);
    teams.get(a.team_id).push(a);
  }
  return [...teams.entries()]
    .sort(
      ([, x], [, y]) =>
        Math.max(...y.map((a) => forecastTotal(round, a))) -
        Math.max(...x.map((a) => forecastTotal(round, a))),
    )
    .map(([, drivers]) => {
      const first = drivers[0];
      return `<div class="participant-team" role="group" aria-label="${esc(constructorName(dataset, first))}" style="--team-color:${teamColor(dataset, first)}"><span class="participant-team-name">${esc(constructorName(dataset, first))}</span><div class="participant-team-drivers">${drivers.map((a) => tile(dataset, probabilities, a, asset, true)).join("")}</div></div>`;
    })
    .join("");
}

export function participantDetail(
  dataset,
  round,
  probabilities,
  population,
  selected,
) {
  const assets = dataset.assets.filter(
    (a) => a.kind === (population === "drivers" ? "DRIVER" : "CONSTRUCTOR"),
  );
  const asset = assets.find((a) => a.id === selected) || assets[0];
  if (!asset) return "";
  const p = probabilities?.[population]?.[asset.id] || {};
  const members =
    asset.kind === "DRIVER"
      ? [asset]
      : dataset.assets.filter(
          (a) => a.kind === "DRIVER" && a.team_id === asset.team_id,
        );
  const after = probabilities?.championship_after;
  const championship =
    after?.status === "ready" ? after[population]?.[asset.id] : null;
  return `<section class="panel participant-detail" style="--team-color:${teamColor(dataset, asset)}"><div class="section-heading"><div><span class="insight-kicker">Race breakdown · R${round.round}</span><h2>${population === "drivers" ? "Driver" : "Team"} deep dive</h2></div></div><div class="participant-browser"><div class="participant-catalogue"><div class="participant-grid" id="insight-participant-grid" role="group" aria-label="Choose ${population === "drivers" ? "driver" : "team"}">${participantTiles(dataset, round, probabilities, population, assets, asset)}</div></div><aside class="participant-prediction outlook-card" aria-label="${esc(asset.name)} predictions"><div class="detail-overview"><div class="detail-identity detail-featured">${image(asset)}<div><h3>${esc(asset.name)}</h3>${asset.kind === "DRIVER" ? `<p>${esc(constructorName(dataset, asset))}</p>` : ""}</div></div><dl class="outlook-stats">${[
    ["Race win", pct(p.win)],
    ["Podium", pct(p.podium)],
    ["Top 10", pct(p.top10)],
    ...championshipStats(championship),
  ]
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
    .join(
      "",
    )}</dl></div><div class="placement-grid">${members.map((a) => placements(a, probabilities?.placements?.[a.id], round.sprint, asset.kind === "CONSTRUCTOR")).join("")}</div></aside></div></section>`;
}

export function teamOutlook(dataset, round, probabilities) {
  const after = probabilities?.championship_after;
  const teams = dataset.assets
    .filter((a) => a.kind === "CONSTRUCTOR")
    .sort(
      (a, b) =>
        (after?.constructors?.[b.id]?.points || 0) -
        (after?.constructors?.[a.id]?.points || 0),
    );
  return `<section class="panel team-outlook"><div class="section-heading"><div><span class="insight-kicker">After R${round.round}</span><h2>Team championship outlook</h2></div></div><div class="team-outlook-grid">${teams
    .map((team) => {
      const row =
        after?.status === "ready" ? after.constructors[team.id] : null;
      return `<article class="outlook-card" style="--team-color:${teamColor(dataset, team)}"><div class="detail-identity">${image(team)}<h3>${esc(team.name)}</h3></div><dl class="outlook-stats">${championshipStats(
        row,
      )
        .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
        .join("")}</dl></article>`;
    })
    .join("")}</div></section>`;
}
