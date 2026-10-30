import test from "node:test";
import assert from "node:assert/strict";
import { insightsMarkup } from "../src/insights.js";

function publication(sprint = false) {
  const participant = {
    key: "AAA",
    name: "Alpha <Test>",
    asset_id: "1",
    races: 1,
    entries: 1,
    classified: 1,
    wins: 1,
    podiums: 1,
    poles: 1,
    sprint_wins: 0,
    sprint_entries: 0,
    points: 25,
    points_complete: true,
    observed: 25,
    remaining: 10,
    projected: 35,
    interval80: [25, 45],
  };
  return {
    season: 2026,
    generated_at: "2026-01-10T00:00:00Z",
    assets: [
      { id: "1", name: participant.name, kind: "DRIVER", team_id: "a" },
      { id: "a", name: "Team A", kind: "CONSTRUCTOR", team_id: "a" },
    ],
    rounds: [
      {
        round: 2,
        name: "Example Grand Prix",
        sprint,
        forecasts: { 1: [3, sprint ? 4 : 0, 12], a: [6, sprint ? 8 : 0, 24] },
      },
    ],
    insights: {
      status: "ready",
      model: "test",
      cutoff: "2026-01-09T00:00:00Z",
      seed: 42,
      simulations: 4000,
      form_samples: { R: 1, S: 0 },
      historical_events: [{}],
      rounds: [
        {
          round: 2,
          drivers: { 1: { win: 0.25, sprint_win: 0.5 } },
          constructors: { a: { win: 0.75 } },
        },
      ],
      pitstops: { status: "unavailable", message: "No verified winners." },
      history: [
        {
          season: 2026,
          rounds: [1],
          expected_rounds: [1, 2],
          complete: false,
          drivers: [participant],
          constructors: [],
        },
      ],
      championship: {
        status: "ready",
        drivers: [participant],
        constructors: [],
      },
    },
  };
}

test("Insights separates probabilities, partial observations, championship ranges and Fantasy scores", () => {
  const html = insightsMarkup(publication());
  assert.match(html, /25\.0%/);
  assert.match(html, /Partial historical coverage/);
  assert.match(html, /Central 80% simulation range/);
  assert.match(html, /Unboosted Fantasy point forecasts/);
  assert.match(html, /No verified winners\./);
  assert.match(html, /Alpha &lt;Test&gt;/);
  assert.doesNotMatch(html, /Alpha <Test>|NaN|undefined|Sprint win<\/option>/);
});

test("Sprint outcomes are format-specific and team probabilities use the published any-car estimate", () => {
  assert.match(
    insightsMarkup(publication(true), { metric: "sprint_win" }),
    /50\.0%/,
  );
  assert.match(
    insightsMarkup(publication(), { metric: "sprint_win" }),
    /25\.0%/,
  );
  const html = insightsMarkup(publication(), { population: "constructors" });
  assert.match(html, /75\.0%/);
  assert.match(html, /At least one car/);
});
