import { esc } from "./views.js";

const number = (n) => (Number.isFinite(n) ? n.toFixed(1) : "Unavailable");

function errorPlot(rows) {
  const values = rows
    .flatMap((r) => [
      r.predicted,
      r.actual,
      r.baseline,
      r.interval?.low,
      r.interval?.high,
    ])
    .filter(Number.isFinite);
  if (!values.length) return "";
  const min = Math.min(0, ...values),
    max = Math.max(1, ...values);
  const x = (n) => 110 + ((n - min) / (max - min)) * 540;
  const height = 54 + rows.length * 34;
  return `<figure class="accuracy-plot"><figcaption>Forecast versus result · Fantasy points<br><span>● Forecast · × Actual · ◇ Last-three baseline · whiskers: earlier-only prediction range</span></figcaption>
    <svg role="img" aria-label="Archived forecast and actual Fantasy points with prediction error bars. Exact values follow in the table." viewBox="0 0 700 ${height}">
    <line x1="${x(0)}" x2="${x(0)}" y1="22" y2="${height - 22}" class="accuracy-zero"/>
    <text x="110" y="16">${number(min)}</text><text x="650" y="16" text-anchor="end">${number(max)} pts</text>
    ${rows
      .map((r, i) => {
        const y = 38 + i * 34;
        return `<g><title>${esc(`${r.season} R${r.round} ${r.session}: forecast ${number(r.predicted)}, actual ${number(r.actual)}, error ${number(r.error)}`)}</title><text x="5" y="${y + 4}">R${r.round} · ${esc(r.session)}</text>${r.interval ? `<path class="accuracy-whisker" d="M${x(r.interval.low)} ${y - 5}v10m0-5H${x(r.interval.high)}m0-5v10"/>` : ""}<line class="accuracy-gap" x1="${x(r.predicted)}" x2="${x(r.actual)}" y1="${y}" y2="${y}"/><circle class="accuracy-prediction" cx="${x(r.predicted)}" cy="${y}" r="4"/><path class="accuracy-actual" d="M${x(r.actual) - 4} ${y - 4}l8 8m0-8-8 8"/>${Number.isFinite(r.baseline) ? `<path class="accuracy-baseline" d="M${x(r.baseline)} ${y - 5}l5 5-5 5-5-5Z"/>` : ""}</g>`;
      })
      .join("")}</svg></figure>`;
}

export function accuracyMarkup(dataset, round, population, selected) {
  const report = dataset.accuracy;
  const kind = population === "constructors" ? "CONSTRUCTOR" : "DRIVER";
  const assets = dataset.assets.filter((a) => a.kind === kind);
  const asset = assets.find((a) => a.id === selected) || assets[0];
  if (!asset) return "";
  const sessions = round.sprint ? ["Q", "S", "R"] : ["Q", "R"];
  const format = round.sprint ? "sprint" : "regular";
  const history = (report?.history || []).filter(
    (r) => r.id === asset.id && r.group.endsWith(`/${format}`),
  );
  const rows = history.slice(-12);
  const cards = sessions
    .map((session) => {
      const group = report?.groups?.[`${kind}/${session}/${format}`];
      const interval = round.intervals?.[asset.id]?.[session];
      const points =
        round.forecasts?.[asset.id]?.[{ Q: 0, S: 1, R: 2 }[session]];
      const maximum = Math.max(
        1,
        group?.paired_model_mae || 0,
        group?.baseline_mae || 0,
      );
      return `<article class="accuracy-card"><h3>${{ Q: "Qualifying", S: "Sprint", R: "Race" }[session]}</h3>
        <p class="accuracy-confidence">${esc(group?.confidence || "Insufficient history")}</p>
        <p>Expected ${number(points)} pts${interval ? ` · range ${number(interval.low)} to ${number(interval.high)}` : " · range unavailable"}</p>
        ${interval ? `<svg viewBox="0 0 240 32" role="img" aria-label="${esc(`Prediction range ${number(interval.low)} to ${number(interval.high)} Fantasy points; forecast ${number(points)}`)}"><path class="accuracy-whisker" d="M16 8v16m0-8h208m0-8v16"/><circle class="accuracy-prediction" cx="120" cy="16" r="5"/></svg>` : ""}
        <p>Historical mean absolute error: <strong>${number(group?.mae)} pts</strong><br>${group?.weekends || 0} weekends · ${group?.observations || 0} population observations</p>
        ${group?.paired_observations ? `<div class="accuracy-mae"><span>Model ${number(group.paired_model_mae)}</span><i style="width:${(group.paired_model_mae / maximum) * 100}%"></i><span>Baseline ${number(group.baseline_mae)}</span><b style="width:${(group.baseline_mae / maximum) * 100}%"></b></div><p>${group.paired_observations} paired observations · lower error is better</p>` : "<p>Baseline comparison awaiting paired results.</p>"}
        <p>${group?.coverage_observations ? `Range covered ${group.coverage_hits} of ${group.coverage_observations} later outcomes across ${group.coverage_weekends} weekends.` : "Range coverage: awaiting later outcomes."}</p></article>`;
    })
    .join("");
  return `<section class="panel accuracy-panel" aria-label="Fantasy forecast accuracy"><div class="section-heading"><div><span class="insight-kicker">Forward evidence · ${format} weekends</span><h2>Forecast accuracy</h2><p>${esc(asset.name)} · select a participant in the deep dive above</p></div></div><div class="accuracy-cards">${cards}</div>${rows.length ? errorPlot(rows) : '<p class="insight-empty" role="status">No settled archived forecasts for this participant and weekend format. Error diagrams will appear after finalized results.</p>'}
    ${rows.length ? `<div class="accuracy-table"><table><caption>Archived predicted-versus-actual values · newest twelve session observations</caption><thead><tr><th>Weekend</th><th>Session</th><th>Forecast</th><th>Actual</th><th>Signed error</th><th>Baseline</th><th>Prediction range</th><th>Published (UTC)</th><th>Finalized (UTC)</th></tr></thead><tbody>${rows.map((r) => `<tr><th>${r.season} R${r.round}</th><td>${esc(r.session)}</td><td>${number(r.predicted)}</td><td>${number(r.actual)}</td><td>${number(r.error)}</td><td>${number(r.baseline)}</td><td>${r.interval ? `${number(r.interval.low)}–${number(r.interval.high)}` : "Unavailable"}</td><td>${esc(r.generated_at)}</td><td>${esc(r.completed_at)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <p class="insight-note">MAE is historical error in Fantasy points, not a confidence percentage. Session statistics cover the selected population; the plot shows this participant. Positive signed error means overprediction. Baseline: ${esc(report?.baseline || "last three completed same-format official weekends")}.</p>
    <p class="insight-note">Whiskers target central coverage of four in five outcomes using the finite-sample conformal rank of earlier weekend-maximum absolute errors. They are conservative population ranges; changing conditions can reduce coverage. They are distinct from MAE. No current outcome is used to draw its own range.</p>
    <dl class="accuracy-definitions">${Object.entries(
      report?.definitions || {
        "Insufficient history": "Fewer than eight archived weekends; no range.",
      },
    )
      .map(
        ([label, definition]) =>
          `<div><dt>${esc(label)}</dt><dd>${esc(definition)}</dd></div>`,
      )
      .join("")}</dl>
    <p class="insight-note">${esc(report?.team_uncertainty || "Team/change uncertainty unavailable without joint evidence")}.</p>${report ? `<p class="insight-note">Model ${esc(report.model)} · ${esc(report.version)} · evaluated ${esc(report.evaluated_at)}</p>` : ""}</section>`;
}
