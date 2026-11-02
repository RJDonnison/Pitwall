import test from "node:test";
import assert from "node:assert/strict";
import { modelFitMarkup } from "../src/model-fit.js";

const part = (gain) => ({
  params: { half_life: 1.5, temperature: 0.8, team_share: 0.35, grid_weight: 2.5 },
  objective: 2.012,
  defaults_objective: 2.035,
  gain_vs_defaults: gain,
  gain_vs_defaults_interval90: [0.0036, 0.0426],
  metrics: { winner_brier: 0.78 },
  default_metrics: { winner_brier: 0.796 },
  latest_decision: { adopted: true, reason: "Adopted <b>x</b>", holdout_gain: 0.01 },
});
const dataset = (gain = 0.0231) => ({
  model: {
    fit: {
      fitted_at: "2026-11-02T10:00:00+00:00",
      evaluated_races: 50,
      last_race: [2026, 18],
      pre_weekend: part(gain),
      post_qualifying: part(0),
      practice: {
        status: "waiting for data: 0 of 12 races carry practice pace",
        weights: { Q: 0.25, SQ: 0.25, R: 0.15 },
      },
    },
  },
});

test("shows the fitted parameters, the backtest gain and its uncertainty", () => {
  const html = modelFitMarkup(dataset());
  assert.match(html, /How the model tunes itself/);
  assert.match(html, /Recency half-life \(races\)<\/dt><dd>1\.50/);
  assert.match(html, /2\.012 against 2\.035/);
  assert.match(html, /90% range -0\.043 to -0\.004/);
  assert.match(html, /0\.796 → 0\.780/);
  assert.match(html, /50 races up to 2026 round 18/);
  assert.match(html, /waiting for data: 0 of 12/);
});

test("says the defaults still win when nothing improved, and escapes text", () => {
  const html = modelFitMarkup(dataset(0));
  assert.match(html, /original defaults are still the best settings found/);
  assert.doesNotMatch(html, /<b>x<\/b>/);
  assert.match(html, /Adopted &lt;b&gt;x&lt;\/b&gt;/);
});

test("renders nothing for a publication without a fit", () => {
  assert.equal(modelFitMarkup({ model: {} }), "");
  assert.equal(modelFitMarkup(undefined), "");
});
