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

function curve(asset, p, label) {
  const values = [...p.positions, p.nc];
  const peak = Math.max(0.01, ...values);
  const coords = values.map((v, i) => [
    i === p.positions.length
      ? 430
      : 30 + (i * 340) / Math.max(1, p.positions.length - 1),
    126 - (98 * v) / peak,
  ]);
  const classified = coords.slice(0, -1);
  const secants = classified
    .slice(1)
    .map(([x, y], i) => (y - classified[i][1]) / (x - classified[i][0]));
  // Monotone cubic interpolation preserves every probability, without bumps
  // beyond neighbouring observations or a flat tangent at every single point.
  const slopes = classified.map((_, i) => {
    if (!i) return secants[0] || 0;
    if (i === classified.length - 1) return secants[i - 1] || 0;
    const a = secants[i - 1],
      b = secants[i];
    return a * b > 0 ? (2 * a * b) / (a + b) : 0;
  });
  const line = classified
    .map(([x, y], i) => {
      if (!i) return `M${x},${y}`;
      const [px, py] = coords[i - 1],
        dx = (x - px) / 3;
      return `C${px + dx},${py + dx * slopes[i - 1]} ${x - dx},${y - dx * slopes[i]} ${x},${y}`;
    })
    .join(" ");
  const ticks = [
    ...new Set([
      0,
      Math.floor((p.positions.length - 1) / 2),
      p.positions.length - 1,
      values.length - 1,
    ]),
  ];
  return `<svg class="placement-curve" viewBox="0 0 460 160" role="group" aria-label="${esc(asset.name)} ${label} position probabilities"><title>${values.map((v, i) => `${i === values.length - 1 ? "NC" : `P${i + 1}`}: ${pct(v)}`).join("; ")}</title><text x="30" y="18">${pct(peak)}</text><path class="curve-grid" d="M30 28H430 M30 77H430 M30 126H430 M400 28V126"/><path class="curve-area" d="${line} L${coords[p.positions.length - 1][0]},126 L30,126Z"/><path class="curve-line" d="${line}"/>${coords
    .map(([x, y], i) => {
      const text = `${i === values.length - 1 ? "NC" : `P${i + 1}`}: ${pct(values[i])}`;
      return `<g class="curve-point" tabindex="0" role="img" aria-label="${text}"><circle class="curve-hit" cx="${x}" cy="${y}" r="8"/><circle cx="${x}" cy="${y}" r="2"/><g class="curve-tooltip" transform="translate(${Math.min(350, Math.max(0, x - 52))},${Math.max(0, y - 38)})"><rect width="104" height="30" rx="4"/><text x="52" y="20" text-anchor="middle">${text}</text></g></g>`;
    })
    .join(
      "",
    )}${ticks.map((i) => `<text x="${coords[i][0]}" y="150" text-anchor="middle">${i === values.length - 1 ? "NC" : `P${i + 1}`}</text>`).join("")}</svg>`;
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
      const outcomes = [...p.positions, p.nc];
      const peak = Math.max(...outcomes);
      const modes = outcomes.flatMap((value, i) =>
        Math.abs(value - peak) < 1e-9
          ? [i === p.positions.length ? "NC" : `P${i + 1}`]
          : [],
      );
      const mostLikely =
        modes.length <= 2 ? modes.join(" / ") : `${modes.length} tied outcomes`;
      return `<section class="placement-session"><div class="placement-session-heading"><h4>${label}</h4><div class="placement-result"><span>Most likely result</span><strong class="position-estimate">${mostLikely}</strong><small>${pct(peak)}${modes.length > 1 ? " each" : ""}</small></div></div><p class="placement-average">Average classified position <strong>${position(p.mean)}</strong></p>${curve(asset, p, label)}</section>`;
    })
    .join("")}</article>`;
}

function championshipStats(row) {
  return [
    [
      "Post-race championship",
      row ? `${points(row.points)} pts` : "Unavailable",
    ],
    ["Post-race championship position", position(row?.standing_mean)],
    ["Weekend points", row ? `+${points(row.round_points)}` : "Unavailable"],
  ];
}

export function participantDetail(
  dataset,
  round,
  probabilities,
  population,
  selected,
  query = "",
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
  return `<section class="panel participant-detail" style="--team-color:${teamColor(dataset, asset)}"><div class="section-heading"><div><span class="insight-kicker">Race breakdown · R${round.round}</span><h2>${population === "drivers" ? "Driver" : "Team"} deep dive</h2></div><span class="detail-round-tag">${assets.length} ${population === "drivers" ? "drivers" : "teams"} · R${round.round}</span></div><div class="participant-browser"><div class="participant-catalogue"><label class="participant-search">Search ${population === "drivers" ? "drivers" : "teams"}<input id="insight-participant-search" type="search" placeholder="${population === "drivers" ? "Name, team or driver code…" : "Team name…"}" value="${esc(query)}" aria-controls="insight-participant-grid" autocomplete="off" /></label><div class="participant-grid" id="insight-participant-grid" role="group" aria-label="Choose ${population === "drivers" ? "driver" : "team"}">${assets
    .map((a) => {
      const search =
        `${a.name} ${a.tla || ""} ${constructorName(dataset, a)}`.toLowerCase();
      return `<button type="button" class="participant-tile" id="insight-participant-${esc(a.id)}" data-insight-entity="${esc(a.id)}" data-participant-search="${esc(search)}" aria-pressed="${a.id === asset.id}" style="--team-color:${teamColor(dataset, a)}" ${search.includes(query.trim().toLowerCase()) ? "" : "hidden"}>${image(a)}<span class="participant-tile-name"><strong>${esc(a.name)}</strong>${a.kind === "DRIVER" ? `<small>${esc(constructorName(dataset, a))}</small>` : ""}</span></button>`;
    })
    .join(
      "",
    )}</div><p id="insight-participant-empty" class="insight-empty" role="status" ${assets.some((a) => `${a.name} ${a.tla || ""} ${constructorName(dataset, a)}`.toLowerCase().includes(query.trim().toLowerCase())) ? "hidden" : ""}>No matching participants. Try a name, team or driver code.</p></div><aside class="participant-prediction" aria-label="${esc(asset.name)} predictions"><div class="detail-overview"><div class="detail-identity detail-featured">${image(asset)}<div><h3>${esc(asset.name)}</h3>${asset.kind === "DRIVER" ? `<p>${esc(constructorName(dataset, asset))}</p>` : ""}</div></div><dl>${[
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
      const drivers = dataset.assets.filter(
        (a) => a.kind === "DRIVER" && a.team_id === team.team_id,
      );
      return `<article style="--team-color:${teamColor(dataset, team)}"><div class="detail-identity">${image(team)}<h3>${esc(team.name)}</h3></div><dl>${championshipStats(
        row,
      )
        .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
        .join(
          "",
        )}</dl><div class="team-member-placements">${drivers.map((a) => `<div>${image(a)}<strong>${esc(a.name)}</strong><span>Average qualifying <b>${position(probabilities?.placements?.[a.id]?.Q?.mean)}</b></span><span>Average race <b>${position(probabilities?.placements?.[a.id]?.R?.mean)}</b></span></div>`).join("")}</div></article>`;
    })
    .join("")}</div></section>`;
}
