import test from "node:test";
import assert from "node:assert/strict";
import { modelFitMarkup } from "../src/model-fit.js";

const part = (gain) => ({
  params: { half_life: 1.5, temperature: 0.8, team_share: 0.35, grid_weight: 2.5 },
  objective: 2.012,
  defaults_objective: 2.035,
  gain_vs_defaults: gain,
  gain_vs_defaults_interval90: [0.0036, 0.0426],
  accuracy: 86.6,
  previous_accuracy: 85.9,
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

test("shows two clearly labelled accuracy scores and no explanation", () => {
  const html = modelFitMarkup(dataset());
  assert.match(html, /<h2>Accuracy<\/h2>/);
  assert.match(html, /Before qualifying · this weekend<\/span><strong class="fit-accuracy">86\.6%/);
  assert.match(html, /Before qualifying · last weekend<\/span><strong class="fit-accuracy">85\.9%/);
  assert.doesNotMatch(html, /replay|First score|Predicting|After qualifying|<details|Last updated/);
  const first = dataset();
  first.model.fit.pre_weekend.previous_accuracy = null;
  assert.match(modelFitMarkup(first), /last weekend<\/span><strong class="fit-accuracy">n\/a/);
});

test("renders nothing for a publication without a fit", () => {
  assert.equal(modelFitMarkup({ model: {} }), "");
  assert.equal(modelFitMarkup(undefined), "");
});
