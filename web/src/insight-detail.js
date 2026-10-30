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

function placements(asset, data, sprint) {
  return `<article class="placement-card"><div class="detail-identity">${image(asset)}<h3>${esc(asset.name)}</h3></div>${[
    "Q",
    ...(sprint ? ["S"] : []),
    "R",
  ]
    .map((kind) => {
      const p = data?.[kind];
      if (!p) return `<p>${kind}: placement estimates unavailable.</p>`;
      const labels = { Q: "Qualifying", R: "Race", S: "Sprint" };
      return `<section class="placement-session"><h4>${labels[kind]}</h4><p>${p.mean === null ? "No classified draws" : `Expected classified position <strong>${points(p.mean)}</strong> · central 80% ${p.interval80.map(points).join("–")}`} · not classified ${pct(p.nc)}</p><ol class="placement-distribution" aria-label="${esc(asset.name)} ${labels[kind]} position probabilities">${p.positions.map((prob, i) => `<li><span>P${i + 1}</span><i style="--prob:${100 * prob}%" aria-hidden="true"></i><strong>${pct(prob)}</strong></li>`).join("")}<li><span>NC</span><i style="--prob:${100 * p.nc}%" aria-hidden="true"></i><strong>${pct(p.nc)}</strong></li></ol></section>`;
    })
    .join("")}</article>`;
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
  const scores = round.forecasts[asset.id];
  return `<section class="panel participant-detail" style="--team-color:${teamColor(dataset, asset)}"><div class="section-heading"><div><span class="insight-kicker">Race breakdown · R${round.round}</span><h2>${population === "drivers" ? "Driver" : "Team"} deep dive</h2></div><label>Explore ${population === "drivers" ? "driver" : "team"}<select id="insight-entity">${assets.map((a) => `<option value="${esc(a.id)}" ${a.id === asset.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select></label></div><div class="detail-overview"><div class="detail-identity detail-featured">${image(asset)}<div><h3>${esc(asset.name)}</h3><p>${esc(constructorName(dataset, asset))}</p></div></div><dl>${[
    ["Race win", pct(p.win)],
    ["Podium", pct(p.podium)],
    ["Top 10", pct(p.top10)],
    ["Unboosted Fantasy", `${points(scores.reduce((a, b) => a + b, 0))} pts`],
  ]
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
    .join(
      "",
    )}</dl></div><div class="placement-grid">${members.map((a) => placements(a, probabilities?.placements?.[a.id], round.sprint)).join("")}</div><p class="insight-note">Position probabilities plus NC sum to 100%. Mean and range condition on classification; NC is not necessarily a mechanical retirement. ${asset.kind === "CONSTRUCTOR" ? "Team probabilities mean at least one car; each driver's placement is shown separately. " : ""}These uncalibrated simulations are real racing outcomes, separate from Fantasy scoring.</p></section>`;
}
