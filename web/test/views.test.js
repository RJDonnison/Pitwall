import test from "node:test";
import assert from "node:assert/strict";
import {
  allocationMarkup,
  profilesMarkup,
  strategyMarkup,
  insightsMarkup,
} from "../src/views.js";

function fixture() {
  const assets = Array.from({ length: 7 }, (_, i) => ({
    id: String(i),
    name: `Selection ${i}`,
    kind: i < 5 ? "DRIVER" : "CONSTRUCTOR",
    team_id: String(i % 2),
    price_tenths_m: 50,
  }));
  const entries = assets.map((a) => ({
    id: a.id,
    base: [2, 0, 8],
    extra: [0, 0, 0],
    sessions: [2, 0, 8],
    points: 10,
  }));
  entries[0] = {
    ...entries[0],
    extra: [2, 0, 8],
    sessions: [4, 0, 16],
    points: 20,
  };
  const round = {
    season: 2099,
    round: 10,
    name: "Example Grand Prix",
    first_session_utc: "2099-01-01T12:00:00Z",
    sprint: false,
    forecasts: Object.fromEntries(assets.map((a) => [a.id, [2, 0, 8]])),
  };
  const data = { assets, rounds: [round] };
  const team = {
    selected: assets.map((a) => a.id),
    budget: 400,
    carry: 0,
    chips: [],
    name: '<img src=x onerror="alert(1)">',
  };
  const result = {
    points: 70,
    status: "Optimal",
    rounds: [
      {
        ...round,
        entries,
        boost: "0",
        x3: null,
        chip: null,
        points: 70,
        penalty: 10,
        transfers: 3,
        in: ["4"],
        out: ["3"],
        cost: 350,
        carry: 0,
      },
    ],
  };
  return { data, team, result };
}

test("strategy displays canonical gross selection scores and net penalty correctly", () => {
  const { data, team, result } = fixture();
  const html = strategyMarkup(data, team, result, false, 0);
  assert.match(html, /70\.0/);
  assert.match(html, /20\.0/);
  assert.match(html, /−10 pts/);
  assert.match(html, /−10\.0 pts/);
  assert.match(html, /2× Boost/);
  assert.equal((html.match(/<th scope="row">/g) || []).length, 7);
  assert.doesNotMatch(html, /NaN|undefined/);
  assert.equal(result.rounds[0].transfer_penalty, undefined);
  assert.equal(result.rounds[0].entries[0].total, undefined);
});

test("local profile names are escaped and over-cap allocation is explicit", () => {
  const { data, team } = fixture();
  assert.doesNotMatch(profilesMarkup(data, [team], 0), /<img/);
  assert.match(profilesMarkup(data, [team], 0), /&lt;img/);
  const html = allocationMarkup(data, { ...team, budget: 300 });
  assert.match(html, /Above the entered budget/);
  assert.match(html, /\$5\.0m over cap/);
});

test("Autopilot displays scenario-dependent extra points without naming a fixed winner", () => {
  const { data, team, result } = fixture();
  result.rounds[0].chip = "autopilot";
  const html = strategyMarkup(data, team, result, false, 0);
  assert.match(html, /Best selected driver/);
  assert.match(html, /10\.0<\/strong><span>expected extra Boost points/);
  assert.equal((html.match(/Autopilot eligible/g) || []).length, 5);
  assert.doesNotMatch(html, /2× Boost<\/span>/);
});

test("Forecasts is explicitly coming soon without showing model scores", () => {
  const { data, team } = fixture();
  data.rounds[0].forecasts["0"] = [-5, 0, 0];
  const html = insightsMarkup(data, team, 0);
  assert.match(html, /Coming soon/);
  assert.doesNotMatch(html, /-5\.0|Forecast round|<table/);
  assert.doesNotMatch(html, /NaN|undefined/);
});
