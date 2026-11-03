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

function params(values, keys) {
  return keys
    .filter((key) => Number.isFinite(values?.[key]))
    .map((key) => `<div><dt>${LABELS[key]}</dt><dd>${fixed(values[key], 2)}</dd></div>`)
    .join("");
}

const pctText = (v) => (Number.isFinite(v) ? `${v.toFixed(1)}%` : "n/a");

function change(now, before) {
  if (!Number.isFinite(now) || !Number.isFinite(before)) return "First score recorded";
  const d = now - before;
  if (Math.abs(d) < 0.05) return `No change from ${pctText(before)} last time`;
  return `${d > 0 ? "Up" : "Down"} ${Math.abs(d).toFixed(1)} points from ${pctText(before)} last time`;
}

function family(title, blurb, part, keys) {
  if (!part) return "";
  const gain = part.gain_vs_defaults;
  const [low, high] = part.gain_vs_defaults_interval90 || [];
  const winner = (m) => fixed(m?.winner_brier);
  const verdict =
    Number.isFinite(gain) && gain > 0
      ? `Tuned settings score ${fixed(part.objective)} against ${fixed(part.defaults_objective)} for the original defaults (lower is better): ${signed(-gain)} overall (90% range ${signed(-high)} to ${signed(-low)}). Win-forecast error ${winner(part.default_metrics)} → ${winner(part.metrics)}.`
      : "The original defaults are still the best settings found.";
  return `<section class="fit-family"><span class="fit-title">${esc(title)}</span><strong class="fit-accuracy">${pctText(part.accuracy)}</strong><p class="fit-change">${esc(change(part.accuracy, part.previous_accuracy))}</p><p class="insight-note">${esc(blurb)}</p><details class="fit-details"><summary>Technical details</summary><dl class="fit-params">${params(part.params, keys)}</dl><p>${verdict}</p><p class="insight-note">Latest check: ${esc(part.latest_decision?.reason || "no decision recorded")}.</p></details></section>`;
}

export function modelFitMarkup(dataset) {
  const fit = dataset?.model?.fit;
  if (!fit) return "";
  const practice = fit.practice || {};
  const weights = practice.weights
    ? `Q ${fixed(practice.weights.Q, 2)} · race ${fixed(practice.weights.R, 2)}`
    : "defaults";
  const last = Array.isArray(fit.last_race) ? `${fit.last_race[0]} round ${fit.last_race[1]}` : "";
  return `<section class="panel model-fit" aria-label="Model accuracy">
    <div class="section-heading"><div><span class="insight-kicker">Refreshed after each race</span><h2>How accurate are the forecasts?</h2><p>Checked on ${esc(fit.evaluated_races)} past races${last ? ` up to ${esc(last)}` : ""}, each predicted using only the races before it. Updated ${esc(when(fit.fitted_at))}.</p></div></div>
    <div class="fit-grid">
      ${family("Before the weekend", "How well finishing order is predicted before practice starts.", fit.pre_weekend, ["half_life", "temperature", "team_share"])}
      ${family("After qualifying", "How well finishing order is predicted once the starting grid is known.", fit.post_qualifying, ["half_life", "temperature", "team_share", "grid_weight"])}
    </div>
    <details class="fit-details"><summary>How is this calculated?</summary><p class="insight-note">Accuracy is 100% minus the average error in predicted finishing positions, so higher is better. Each finished race, the model may adjust its settings by one small step, but only if races it was not tuned on confirm the change helps. Practice pace: ${esc(practice.status || "no practice evidence yet")} (weights ${esc(weights)}).</p></details>
  </section>`;
}
