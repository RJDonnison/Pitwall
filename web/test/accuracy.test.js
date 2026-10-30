import test from "node:test";
import assert from "node:assert/strict";
import { accuracyMarkup } from "../src/accuracy.js";

const dataset = {
  assets: [
    { id: "1", name: "Alpha <One>", kind: "DRIVER" },
    { id: "a", name: "Team", kind: "CONSTRUCTOR" },
  ],
  accuracy: {
    model: "test",
    version: "v1",
    evaluated_at: "2026-10-30",
    baseline: "Last-three same-format weekends",
    definitions: {
      "Provisional range": "Eight earlier weekends; awaiting forward coverage.",
    },
    groups: {
      "DRIVER/R/regular": {
        confidence: "Provisional range",
        mae: 3,
        weekends: 8,
        observations: 160,
        paired_observations: 160,
        paired_model_mae: 3,
        baseline_mae: 5,
        coverage_observations: 0,
      },
    },
    history: [
      {
        id: "1",
        season: 2026,
        round: 19,
        session: "R",
        group: "DRIVER/R/regular",
        predicted: 15,
        actual: -5,
        error: 20,
        baseline: 12,
        interval: { low: -10, high: 20 },
        generated_at: "2026-10-01T00:00:00Z",
        completed_at: "2026-10-04T20:00:00Z",
      },
    ],
  },
};
const round = {
  sprint: false,
  forecasts: { 1: [2, 0, 15] },
  intervals: { 1: { R: { low: -10, high: 40 } } },
};

test("accuracy renders accessible error bars, exact outcomes, baseline and defined text labels", () => {
  const html = accuracyMarkup(dataset, round, "drivers", "1");
  assert.match(html, /Provisional range/);
  assert.match(html, /accuracy-whisker/);
  assert.match(html, /accuracy-actual/);
  assert.match(html, /accuracy-baseline/);
  assert.match(html, /<table>/);
  assert.match(html, />-5\.0<\/td>/);
  assert.match(html, /Alpha &lt;One&gt;/);
  assert.match(html, /not a confidence percentage/);
  assert.doesNotMatch(html, /NaN|undefined|confidence.*\d+%/);
});

test("sparse evidence and other populations or formats cannot invent ranges or diagrams", () => {
  const html = accuracyMarkup(
    dataset,
    { ...round, sprint: true },
    "constructors",
    "1",
  );
  assert.match(html, /Insufficient history/);
  assert.match(html, /No settled archived forecasts/);
  assert.doesNotMatch(html, /<svg|<table>/);
});
