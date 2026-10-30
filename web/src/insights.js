import { esc, teamColor, helmet, car, constructorName } from "./views.js";
import { portrait } from "./visuals.js";
import { participantDetail, teamOutlook } from "./insight-detail.js";
import { accuracyMarkup } from "./accuracy.js";
import {
  insightHero,
  weatherBriefing,
  fantasyChart,
  championshipChart,
} from "./insight-visuals.js";

const percent = (n) => `${(n * 100).toFixed(1)}%`;
const stamp = (value) =>
  new Date(value).toLocaleString(undefined, {
    timeZone: "UTC",
    dateStyle: "medium",
    timeStyle: "short",
  }) + " UTC";
const option = (value, label, current) =>
  `<option value="${esc(value)}" ${String(value) === String(current) ? "selected" : ""}>${esc(label)}</option>`;
const empty = (message) =>
  `<p class="insight-empty" role="status">${esc(message)}</p>`;

function identity(dataset, a) {
  return `<span class="insight-identity"><span class="insight-portrait">${portrait(a, a.kind === "DRIVER" ? helmet() : car())}</span><span><strong>${esc(a.name)}</strong><small>${esc(a.kind === "DRIVER" ? constructorName(dataset, a) : "Constructor")}</small></span></span>`;
}

function probabilityMarkup(dataset, probabilities, population, metric) {
  const rows = dataset.assets
    .filter(
      (a) => a.kind === (population === "drivers" ? "DRIVER" : "CONSTRUCTOR"),
    )
    .map((a) => ({ a, value: probabilities?.[population]?.[a.id]?.[metric] }))
    .filter((r) => Number.isFinite(r.value))
    .sort((a, b) => b.value - a.value || a.a.name.localeCompare(b.a.name));
  if (!rows.length) return empty("No supported probability for this session.");
  return `<ol class="probability-list">${rows.map(({ a, value }, i) => `<li style="--team-color:${teamColor(dataset, a)}"><span class="probability-position">${i + 1}</span>${identity(dataset, a)}<strong>${percent(value)}</strong><span class="probability-track" aria-hidden="true"><i style="width:${value * 100}%"></i></span></li>`).join("")}</ol>`;
}

function pitstopMarkup(dataset, pit) {
  if (pit.status !== "ready") return empty(pit.message);
  const rows = dataset.assets
    .filter((a) => a.kind === "CONSTRUCTOR")
    .sort((a, b) => pit.probabilities[b.id] - pit.probabilities[a.id]);
  return `<ol class="pitstop-list">${rows.map((a) => `<li style="--team-color:${teamColor(dataset, a)}">${identity(dataset, a)}<strong>${percent(pit.probabilities[a.id])}</strong><span class="probability-track" aria-hidden="true"><i style="width:${pit.probabilities[a.id] * 100}%"></i></span></li>`).join("")}</ol><p class="insight-note"><a href="${esc(pit.source)}" target="_blank" rel="noopener noreferrer">${pit.stop_samples ? "OpenF1 stationary observations" : "Official finalized winner labels"}</a> · checked ${esc(stamp(pit.checked_at))}</p>`;
}

export function insightsMarkup(dataset, state = {}) {
  const insight = dataset?.insights;
  if (insight?.status !== "ready")
    return `<div class="page-heading"><h1>Race Insights</h1></div><section class="panel">${empty(insight?.message || "Race Insights is unavailable in this publication. Refresh the public history and publish new forecasts.")}</section>`;
  const population = state.population || "drivers";
  const round =
    dataset.rounds.find((r) => r.round === Number(state.round)) ||
    dataset.rounds[0];
  const probabilities = insight.rounds.find((r) => r.round === round.round);
  const metrics = {
    win: "Race win",
    podium: "Race podium",
    pole: "Pole position",
    top10: "Race top 10",
    nc: "Not classified",
    ...(round.sprint
      ? {
          sprint_win: "Sprint win",
          sprint_podium: "Sprint podium",
          sprint_top10: "Sprint top 10",
          sprint_nc: "Sprint not classified",
        }
      : {}),
  };
  const metric = Object.hasOwn(metrics, state.metric) ? state.metric : "win";
  return `<div class="insights-page">${insightHero(dataset, round, insight)}
    <div class="insight-toolbar"><label>Forecast round<select id="insight-round">${dataset.rounds.map((r) => option(r.round, `R${r.round} · ${r.name}${r.sprint ? " · Sprint" : ""}`, round.round)).join("")}</select></label><div class="segments" role="group" aria-label="Insights population">${["drivers", "constructors"].map((p) => `<button data-insight-population="${p}" aria-pressed="${population === p}">${p === "drivers" ? "Drivers" : "Teams"}</button>`).join("")}</div><p>Historical cutoff<br><strong>${esc(stamp(insight.cutoff_utc || insight.cutoff))}</strong></p></div>
    ${weatherBriefing(round)}
    <div class="insight-workbench">${fantasyChart(dataset, round, population)}${championshipChart(dataset, insight, population)}</div>
    <div class="insight-probability-grid"><section class="panel"><div class="section-heading"><div><h2>Race probabilities</h2><p>${population === "constructors" ? "At least one car achieves the selected outcome." : "Each driver's chance of the selected outcome."}</p></div><label><span class="sr-only">Probability outcome</span><select id="insight-metric">${Object.entries(
      metrics,
    )
      .map(([key, label]) => option(key, label, metric))
      .join(
        "",
      )}</select></label></div>${probabilityMarkup(dataset, probabilities, population, metric)}</section><aside class="panel pitstop-panel"><div class="section-heading"><div><h2>Fastest pit stop</h2></div></div>${pitstopMarkup(dataset, insight.pitstops)}</aside></div>
    ${participantDetail(dataset, round, probabilities, population, state.entity)}
    ${teamOutlook(dataset, round, probabilities)}
    ${accuracyMarkup(dataset, round, population, state.entity)}
  </div>`;
}
