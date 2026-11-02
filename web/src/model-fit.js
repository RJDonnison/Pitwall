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

function family(title, part, keys) {
  if (!part) return "";
  const gain = part.gain_vs_defaults;
  const [low, high] = part.gain_vs_defaults_interval90 || [];
  const winner = (m) => fixed(m?.winner_brier);
  const verdict =
    Number.isFinite(gain) && gain > 0
      ? `Tuned settings score ${fixed(part.objective)} against ${fixed(part.defaults_objective)} for the original defaults (lower is better): ${signed(-gain)} overall (90% range ${signed(-high)} to ${signed(-low)}). Win-forecast error ${winner(part.default_metrics)} → ${winner(part.metrics)}.`
      : "The original defaults are still the best settings found.";
  return `<section class="fit-family"><h3>${esc(title)}</h3><dl class="fit-params">${params(part.params, keys)}</dl><p>${verdict}</p><p class="insight-note">Latest check: ${esc(part.latest_decision?.reason || "no decision recorded")}.</p></section>`;
}

export function modelFitMarkup(dataset) {
  const fit = dataset?.model?.fit;
  if (!fit) return "";
  const practice = fit.practice || {};
  const weights = practice.weights
    ? `Q ${fixed(practice.weights.Q, 2)} · race ${fixed(practice.weights.R, 2)}`
    : "defaults";
  const last = Array.isArray(fit.last_race) ? `${fit.last_race[0]} round ${fit.last_race[1]}` : "";
  return `<section class="panel model-fit" aria-label="Model tuning">
    <div class="section-heading"><div><span class="insight-kicker">Backtested · refit after each race</span><h2>How the model tunes itself</h2><p>Last fitted ${esc(when(fit.fitted_at))} on ${esc(fit.evaluated_races)} races${last ? ` up to ${esc(last)}` : ""}.</p></div></div>
    <div class="fit-grid">
      ${family("Before the weekend", fit.pre_weekend, ["half_life", "temperature", "team_share"])}
      ${family("After qualifying (known grid)", fit.post_qualifying, ["half_life", "temperature", "team_share", "grid_weight"])}
      <section class="fit-family"><h3>Practice pace</h3><p>Weights: ${esc(weights)}.</p><p class="insight-note">${esc(practice.status || "No practice evidence yet")}.</p></section>
    </div>
    <p class="insight-note">Each finished race, the settings move at most one step, and only if races not used to choose the step confirm it is no worse and clearly better overall. Scores are Brier-type errors from walk-forward backtests: every race is predicted only from earlier races.</p>
  </section>`;
}
