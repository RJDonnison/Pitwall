import test from "node:test";
import assert from "node:assert/strict";
import {
  allocationMarkup,
  profilesMarkup,
  strategyMarkup,
  insightsMarkup,
  registryCardMarkup,
  transfersMarkup,
  heroMarkup,
} from "../src/views.js";
import { footerMarkup } from "../src/visuals.js";

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
test("Strategy updates automatically without manual calculation controls", () => {
  const { data, team } = fixture();
  const html = strategyMarkup(data, team, null, false, 0);
  assert.match(html, /automatically/);
  assert.doesNotMatch(
    html,
    /id="replan"|Calculate changes|Recalculate|href="#garage"/,
  );
  assert.match(
    strategyMarkup(data, team, null, false, 0, "Bad budget"),
    /Bad budget/,
  );
});

test("regular Boost uses its driver's real portrait, not an arbitrary Autopilot winner", () => {
  const { data, team, result } = fixture();
  data.assets[0].id = "131";
  team.selected[0] = "131";
  data.rounds[0].forecasts["131"] = data.rounds[0].forecasts["0"];
  result.rounds[0].entries[0].id = "131";
  result.rounds[0].boost = "131";
  const html = strategyMarkup(data, team, result, false, 0);
  assert.match(html, /class="boost-backdrop"[^>]*><img[^>]*media\/131.webp/);
  result.rounds[0].chip = "autopilot";
  const automatic = strategyMarkup(data, team, result, false, 0);
  assert.match(automatic, /class="boost-candidates"/);
  assert.doesNotMatch(automatic, /class="boost-backdrop"/);
});

test("roster changes separate removal and arrival lists without implying swap pairs", () => {
  const { data } = fixture();
  const html = transfersMarkup(data, ["0", "5"], ["1", "6"]);
  assert.match(html, /aria-label="Remove selections"/);
  assert.match(html, /aria-label="Bring in selections"/);
  assert.match(
    html,
    /tabindex="0" role="region" aria-label="Roster changes; scroll/,
  );
  assert.equal((html.match(/<li>/g) || []).length, 4);
  assert.match(html, /Selection 0/);
  assert.match(html, /Selection 6/);
  assert.match(transfersMarkup(data, [], []), /Keep the current roster/);
});

test("track and weather context distinguish sourced air forecasts from model inputs", () => {
  const { data, team } = fixture();
  data.rounds[0].track_spec = {
    length_km: 4.304,
    race_laps: 71,
    race_distance_km: 305.354,
    season: 2026,
    source: "https://www.formula1.com/en/racing/2026/mexico/circuit",
  };
  data.rounds[0].weather = {
    status: "available",
    air_min_c: 12,
    air_max_c: 25,
    daily_rain_probability_max: 35,
    wind_max_kmh: 18,
    start_date: "2026-10-31",
    end_date: "2026-11-01",
    fetched_at: "2026-10-30T10:00:00Z",
  };
  const html = heroMarkup(data, team, null);
  assert.match(html, /4\.304/);
  assert.match(html, /71 <small>laps/);
  assert.match(html, /12–25° <small>air/);
  assert.match(html, /35%/);
  assert.doesNotMatch(html, /Weather context only|not used in point estimates/);
  assert.doesNotMatch(html, /<a\b|2026-10-31|2026-11-01|UTC days|Open-Meteo/);
  data.rounds[0].weather = { status: "outside_horizon" };
  const later = heroMarkup(data, team, null);
  assert.match(later, /Outside the 16-day/);
  assert.doesNotMatch(later, /12–25°|35%/);
});

test("editorial footer retains public data status, privacy and source credits", () => {
  const html = footerMarkup();
  assert.match(html, /Think in seasons/);
  assert.match(html, /One joint plan/);
  assert.match(html, /<h3>Forecasts<\/h3>/);
  assert.match(html, /Your teams stay here/);
  assert.match(html, /id="publication-status"/);
  assert.match(html, /TracingInsights/);
  assert.doesNotMatch(html, /id="refresh"/);
});

test("rounds stay expanded, use chip icons and omit redundant marketing text", () => {
  const { data, team, result } = fixture();
  result.rounds[0].chip = "wildcard";
  const html = strategyMarkup(data, team, result);
  assert.doesNotMatch(
    html,
    /round-disclosure|<details|Not a promise|Conditional optimality|vs 2×-only reference|Positive session contributions shown|All seven selections|Unlimited transfers within/,
  );
  assert.match(html, /class="plan-chip chip-wildcard"><svg/);
  assert.match(html, /class="transfer-status">OUT/);
  assert.match(html, /class="transfer-status">IN/);
  assert.match(html, /class="transfer-estimate negative"[^>]*>−10\.0/);
  assert.match(html, /class="transfer-estimate positive"[^>]*>\+10\.0/);
});

test("registry shows unboosted next-round points and team colours for both kinds", () => {
  const { data, team } = fixture();
  data.assets[6].name = "Ferrari";
  for (const a of [data.assets[0], data.assets[6]]) {
    const html = registryCardMarkup(data, team, a);
    assert.match(html, /--team-color:#b81b25/);
    assert.match(html, /<strong>10\.0<\/strong> est\. pts/);
    assert.match(html, /class="registry-add"/);
    assert.match(html, /aria-label="Remove /);
    assert.match(html, /aria-pressed="true"/);
    assert.doesNotMatch(html, /disabled|>Constructor<\/span>/);
  }
  const extra = { ...data.assets[0], id: "extra", name: "Extra driver" };
  data.assets.push(extra);
  data.rounds[0].forecasts.extra = [-5, 0, 3];
  const html = registryCardMarkup(data, team, extra);
  assert.match(html, /<strong>-2\.0<\/strong> est\. pts/);
  assert.match(html, /aria-label="Add Extra driver"/);
  assert.match(html, /disabled/);
});
