import { esc } from "./views.js";

const fixed = (value, digits = 3) =>
  Number.isFinite(value) ? Number(value).toFixed(digits) : "n/a";
const signed = (value, digits = 3) =>
  Number.isFinite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(digits)}` : "n/a";
const when = (value) =>
  value
    ? new Date(value).toLocaleDateString(undefined, {
        timeZone: "UTC",
        dateStyle: "medium",
      })
    : "never";

const LABELS = {
  half_life: "Recency half-life (races)",
  temperature: "Spread of outcomes",
  team_share: "Shared car effect",
  grid_weight: "Starting-grid weight",
};

const pctText = (v) => (Number.isFinite(v) ? `${v.toFixed(1)}%` : "n/a");

function change(now, before) {
  if (!Number.isFinite(now) || !Number.isFinite(before))
    return "First score recorded. The next update will show how it changed.";
  const d = now - before;
  if (Math.abs(d) < 0.05) return `Unchanged since the last update (${pctText(before)}).`;
  return `${d > 0 ? "Up" : "Down"} ${Math.abs(d).toFixed(1)} points since the last update (${pctText(before)}).`;
}

function family(title, blurb, part) {
  if (!part) return "";
  return `<section class="fit-family"><span class="fit-title">${esc(title)}</span><strong class="fit-accuracy">${pctText(part.accuracy)}</strong><p class="fit-change">${esc(change(part.accuracy, part.previous_accuracy))}</p><p class="insight-note">${esc(blurb)}</p></section>`;
}

export function modelFitMarkup(dataset) {
  const fit = dataset?.model?.fit;
  if (!fit) return "";
  const last = Array.isArray(fit.last_race) ? ` up to ${fit.last_race[0]} round ${fit.last_race[1]}` : "";
  return `<section class="panel model-fit" aria-label="Forecast accuracy">
    <div class="section-heading"><div><span class="insight-kicker">Updated after every race</span><h2>How accurate are the forecasts?</h2><p>We replay ${esc(fit.evaluated_races)} past races${esc(last)}. For each one, the model predicts the finishing order using only the races before it, then we compare with what really happened. A higher score means the predicted order was closer. Last updated ${esc(when(fit.fitted_at))}.</p></div></div>
    <div class="fit-grid">
      ${family("Before the weekend", "Predicting the finishing order before the weekend starts.", fit.pre_weekend)}
      ${family("After qualifying", "Predicting the finishing order once the starting grid is known.", fit.post_qualifying)}
    </div>
  </section>`;
}
