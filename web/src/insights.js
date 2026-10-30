import {
  esc,
  points,
  teamColor,
  helmet,
  car,
  constructorName,
} from "./views.js";
import { portrait, circuitMarkup } from "./visuals.js";

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
const table = (caption, heads, rows) =>
  `<div class="table-scroll insight-table" tabindex="0" role="region" aria-label="${esc(caption)}; scroll for all columns"><table><caption class="sr-only">${esc(caption)}</caption><thead><tr>${heads.map((h) => `<th scope="col">${h}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;

function identity(dataset, row) {
  const a = dataset.assets.find((a) => a.id === row.asset_id);
  return `<span class="insight-identity">${a ? `<span class="insight-portrait">${portrait(a, a.kind === "DRIVER" ? helmet() : car())}</span>` : ""}<span><strong>${esc(row.name)}</strong><small>${a ? esc(a.kind === "DRIVER" ? constructorName(dataset, a) : "Constructor") : "Historical participant · no future starts assumed"}</small></span></span>`;
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
  return `<ol class="probability-list">${rows.map(({ a, value }, i) => `<li style="--team-color:${teamColor(dataset, a)}"><span class="probability-position">${i + 1}</span>${identity(dataset, { asset_id: a.id, name: a.name })}<strong>${percent(value)}</strong><span class="probability-track" aria-hidden="true"><i style="width:${value * 100}%"></i></span></li>`).join("")}</ol>`;
}

function pitstopMarkup(dataset, pit) {
  if (pit.status !== "ready") return empty(pit.message);
  const rows = dataset.assets
    .filter((a) => a.kind === "CONSTRUCTOR")
    .sort((a, b) => pit.probabilities[b.id] - pit.probabilities[a.id]);
  return `<p class="insight-note">Fastest stationary stop of the Grand Prix. ${pit.samples} finalized official winners; one prior win per team.</p><ol class="pitstop-list">${rows.map((a) => `<li><span>${esc(a.name)}</span><strong>${percent(pit.probabilities[a.id])}</strong><span class="probability-track" aria-hidden="true"><i style="width:${pit.probabilities[a.id] * 100}%"></i></span></li>`).join("")}</ol><details class="insight-evidence"><summary>Winner evidence & source</summary><p>Checked ${esc(stamp(pit.checked_at))}. <a href="${esc(pit.source)}" target="_blank" rel="noopener noreferrer">Official F1 Predict finalized labels</a>.</p><ul>${pit.evidence.map((r) => `<li>Round ${r.gameday_id}: ${esc(r.team_name)} · published ${esc(stamp(r.published_at))}</li>`).join("")}</ul></details>`;
}

function championshipMarkup(dataset, insight, population) {
  const champ = insight.championship;
  if (champ.status !== "ready") return empty(champ.message);
  const rows = champ[population];
  const max = Math.max(1, ...rows.map((r) => r.interval80[1]));
  return table(
    "Projected championship points",
    [
      "Participant",
      "Observed",
      "Expected remaining",
      "Projected final",
      "Central 80% simulation range",
    ],
    rows
      .map(
        (r) =>
          `<tr><th scope="row">${identity(dataset, r)}</th><td>${points(r.observed)}</td><td>+${points(r.remaining)}</td><td><strong>${points(r.projected)}</strong></td><td class="range-cell"><span>${points(r.interval80[0])}–${points(r.interval80[1])}</span><span class="projection-range" aria-hidden="true"><i style="left:${(100 * r.interval80[0]) / max}%;width:${(100 * (r.interval80[1] - r.interval80[0])) / max}%"></i><b style="left:${(100 * r.projected) / max}%"></b></span></td></tr>`,
      )
      .join(""),
  );
}

function historicalMarkup(dataset, history, population, sort, query) {
  const rows = [...history[population]].sort((a, b) =>
    sort === "name"
      ? a.name.localeCompare(b.name)
      : b[sort] - a[sort] || a.name.localeCompare(b.name),
  );
  return table(
    "Observed historical statistics",
    [
      "Participant",
      "GP weekends",
      "Car entries",
      "Classified",
      "Wins",
      "Podiums",
      "Poles",
      "Sprint wins / entries",
      "Real F1 points",
    ],
    rows
      .map(
        (r) =>
          `<tr data-history-name="${esc(r.name.toLowerCase())}" ${query && !r.name.toLowerCase().includes(query.toLowerCase()) ? "hidden" : ""}><th scope="row">${identity(dataset, r)}</th><td>${r.races}</td><td>${r.entries}</td><td>${r.classified} / ${r.entries}</td><td>${r.wins}</td><td>${r.podiums}</td><td>${r.poles}</td><td>${r.sprint_wins} / ${r.sprint_entries}</td><td>${r.points_complete ? points(r.points) : "Incomplete"}</td></tr>`,
      )
      .join(""),
  );
}

function fantasyMarkup(dataset, round, population) {
  return table(
    "Unboosted Fantasy point forecasts",
    [
      "Selection",
      "Qualifying",
      ...(round.sprint ? ["Sprint"] : []),
      "Race",
      "Weekend total",
    ],
    dataset.assets
      .filter(
        (a) => a.kind === (population === "drivers" ? "DRIVER" : "CONSTRUCTOR"),
      )
      .sort((a, b) => b.id.localeCompare(a.id))
      .map((a) => {
        const scores = round.forecasts[a.id];
        return `<tr><th scope="row">${identity(dataset, { asset_id: a.id, name: a.name })}</th><td>${points(scores[0])}</td>${round.sprint ? `<td>${points(scores[1])}</td>` : ""}<td>${points(scores[2])}</td><td><strong>${points(scores.reduce((a, b) => a + b, 0))}</strong></td></tr>`;
      })
      .join(""),
  );
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
  const history =
    insight.history.find((h) => h.season === Number(state.season)) ||
    insight.history[0];
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
  const sort = state.sort || "points";
  return `<div class="insights-page"><div class="page-heading insight-heading"><div><h1>Race Insights</h1><p>Results behind us. Possibilities ahead.</p></div><span class="tag">Uncalibrated model</span></div>
    <div class="insight-toolbar"><label>Forecast round<select id="insight-round">${dataset.rounds.map((r) => option(r.round, `R${r.round} · ${r.name}${r.sprint ? " · Sprint" : ""}`, round.round)).join("")}</select></label><div class="segments" role="group" aria-label="Insights population">${["drivers", "constructors"].map((p) => `<button data-insight-population="${p}" aria-pressed="${population === p}">${p === "drivers" ? "Drivers" : "Teams"}</button>`).join("")}</div><p>Historical cutoff<br><strong>${esc(stamp(insight.cutoff))}</strong></p></div>
    <section class="insight-race-strip"><div><span class="eyebrow">Round ${round.round} · ${round.sprint ? "Sprint" : "Regular"} weekend</span><h2>${esc(round.name)}</h2><p>${insight.simulations.toLocaleString()} joint simulations · ${insight.form_samples.R} recent GPs${round.sprint ? ` · ${insight.form_samples.S} Sprints` : ""}</p></div>${circuitMarkup(round.name)}</section>
    <div class="insight-probability-grid"><section class="panel"><div class="section-heading"><div><h2>Race probabilities</h2><p>${population === "constructors" ? "At least one car achieves the selected outcome." : "Each driver's chance of the selected outcome."}</p></div><label><span class="sr-only">Probability outcome</span><select id="insight-metric">${Object.entries(
      metrics,
    )
      .map(([key, label]) => option(key, label, metric))
      .join(
        "",
      )}</select></label></div>${probabilityMarkup(dataset, probabilities, population, metric)}<p class="insight-note">${population === "constructors" ? "Team outcomes overlap. " : ""}Not classified is a result classification, not necessarily a mechanical retirement. Probabilities are model estimates.</p></section>
    <aside class="panel pitstop-panel"><div class="section-heading"><div><h2>Fastest pit stop</h2><p>Stationary-stop winner probability</p></div></div>${pitstopMarkup(dataset, insight.pitstops)}</aside></div>
    <section class="panel"><div class="section-heading"><div><h2>Championship horizon</h2><p>${dataset.season} real F1 points · all ${dataset.rounds.length} remaining published rounds</p></div><span class="tag">Observed + simulated</span></div>${championshipMarkup(dataset, insight, population)}<p class="insight-note">Full-distance GP points (25–18–15–12–10–8–6–4–2–1) and Sprint points (8–1); no fastest-lap bonus. Ranges show the middle 80% of joint simulated seasons, not calibrated confidence. Historical participants retain their earned points. Rows are ordered by expected points, not official countback standings.</p></section>
    <section class="panel"><div class="section-heading"><div><h2>Historical record</h2><p>Observed results · GP counts exclude Sprints</p></div><label>Season<select id="insight-season">${insight.history.map((h) => option(h.season, h.season, history.season)).join("")}</select></label></div><div class="history-tools"><label><span class="sr-only">Search historical participants</span><input id="insight-search" type="search" placeholder="Search historical participants…" value="${esc(state.query || "")}"/></label><label>Order by<select id="insight-sort">${Object.entries(
      {
        points: "Real F1 points",
        wins: "GP wins",
        podiums: "GP podiums",
        poles: "Poles",
        name: "Name",
      },
    )
      .map(([k, v]) => option(k, v, sort))
      .join(
        "",
      )}</select></label></div><p class="insight-coverage ${history.complete ? "" : "partial"}">${history.complete ? "Complete pre-cutoff season coverage" : "Partial historical coverage — not full-season totals"}: ${history.rounds.length} of ${history.expected_rounds.length} completed GPs · rounds ${history.rounds.join(", ")}.</p>${historicalMarkup(dataset, history, population, sort, state.query || "")}<p id="history-empty" class="insight-empty" hidden>No matching participants. Try another name.</p><p class="insight-note">Constructor entries, podiums and classification count individual cars; GP weekends count each event once. Sprint entries and wins are separate. Real F1 points include both Race and Sprint results; qualifying awards no championship points.</p></section>
    <details class="panel fantasy-insights"><summary>Fantasy forecast breakdown · R${round.round}</summary><p class="insight-note">Predicted Fantasy points, separate from real F1 points above. No Boost, chips or transfer penalties. ${esc(round.name)}.</p>${fantasyMarkup(dataset, round, population)}</details>
    <details class="panel insight-methodology"><summary>Model, uncertainty & data sources</summary><div><p>Model ${esc(insight.model)}. Seed ${insight.seed}; ${insight.simulations.toLocaleString()} simulations. Historical records end strictly before ${esc(stamp(insight.cutoff))}. One fixed cutoff applies to every future round. No selected-weekend results enter these forecasts.</p><p>Prior-smoothed recent qualifying, race and distinct Sprint form feed a whole-weekend bootstrap, shared driver-performance noise and session-specific noise. The current roster and historical form remain fixed across the horizon; track adjustments use only earlier cached telemetry. Weather is display-only. Future race draws are independent across weekends; long-term form changes and future substitutions are not modeled.</p><p>Probabilities and simulation ranges are uncalibrated. Sparse history is shrunk toward priors. Zero sampled outcomes does not prove impossibility. These are scenario estimates, not measured accuracy or a confidence score. Fantasy predictions use their own scoring model.</p><p>Observed classifications and session championship points: <a href="https://docs.fastf1.dev/" target="_blank" rel="noopener noreferrer">FastF1 public results</a>. These are sums of recorded session points, not an independently reconciled FIA standings feed; subsequent non-session championship adjustments may differ. Fastest pit stops use finalized official F1 Predict winner labels with a symmetric one-win-per-team prior. They do not estimate stop duration or use pit-lane transit times.</p><p>${insight.historical_events.length} archived events available. Publication ${esc(stamp(dataset.generated_at))}; six-hour freshness applies. Missing history is reported as unavailable rather than replaced with zero.</p></div></details></div>`;
}
