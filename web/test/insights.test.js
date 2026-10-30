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
    max_final: 50,
    title_eligible: true,
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
          championship_after: {
            status: "ready",
            drivers: {
              1: {
                points: 40,
                points_before: 25,
                round_points: 15,
                standing_mean: 1.4,
              },
            },
            constructors: {
              a: {
                points: 80,
                points_before: 50,
                round_points: 30,
                standing_mean: 2.2,
              },
            },
          },
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

test("Insights keeps probabilities, championship ranges and Fantasy scores without accordions or history", () => {
  const html = insightsMarkup(publication());
  assert.match(html, /25\.0%/);
  assert.match(html, /<dt>80% range<\/dt><dd>25.0–45.0/);
  assert.match(html, /Post-race championship/);
  assert.match(html, /No verified winners\./);
  assert.match(html, /Alpha &lt;Test&gt;/);
  assert.doesNotMatch(html, /Alpha <Test>|NaN|undefined|Sprint win<\/option>/);
  assert.doesNotMatch(
    html,
    /<details|<summary|Historical record|insight-season|insight-sort|id="insight-entity"/,
  );
  assert.ok(
    html.indexOf("<h2>Race probabilities") <
      html.indexOf("<h2>Driver deep dive"),
  );
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

test("The selected round owns its sourced hero, map and daily weather briefing", () => {
  const data = publication();
  const mexico = data.rounds[0];
  mexico.name = "Mexico City Grand Prix";
  mexico.track_spec = {
    race_laps: 71,
    length_km: 4.304,
    race_distance_km: 305.354,
  };
  mexico.weather = {
    status: "available",
    air_min_c: 12,
    air_max_c: 25,
    daily_rain_probability_max: 35,
    wind_max_kmh: 18,
    start_date: "2026-10-30",
    end_date: "2026-10-30",
    fetched_at: "2026-10-30T00:00:00Z",
    daily: [
      {
        date: "2026-10-30",
        air_min_c: 12,
        air_max_c: 25,
        rain_probability: 35,
        wind_max_kmh: 18,
      },
    ],
  };
  data.rounds.push({
    ...mexico,
    round: 3,
    name: "Las Vegas Grand Prix",
    weather: { status: "outside_horizon" },
  });
  const first = insightsMarkup(data);
  assert.match(first, /mx-1962-hero.webp/);
  assert.match(first, /mx-1962-map-2026.webp/);
  assert.match(first, /1:17.774/);
  assert.match(first, /305.354 km/);
  assert.match(first, /Circuit sectors/);
  assert.match(first, /35% rain · 18 km\/h wind/);
  assert.doesNotMatch(
    first,
    /insight-ticker|insight-hero-badges|insight-weather-source|2026 replaces DRS/,
  );
  const other = insightsMarkup(data, { round: 3 });
  assert.match(other, /us-2023-hero.webp/);
  assert.match(other, /Open detailed official map/);
  assert.match(other, /Outside the 16-day forecast window/);
  assert.doesNotMatch(
    other,
    /35% rain|mx-1962-map-2026.webp|overtake detection and activation points|NaN|undefined/,
  );
  data.season = 2027;
  assert.doesNotMatch(insightsMarkup(data), /map-2026.webp|1:17.774/);
});

test("driver and team deep dives show selected participants and classified position distributions", () => {
  const data = publication();
  data.assets[0].team_id = "team-a";
  data.assets[1].team_id = "team-a";
  data.insights.rounds[0].placements = {
    1: {
      Q: { mean: 1.2, interval80: [1, 2], positions: [0.8, 0.2], nc: 0 },
      R: { mean: 1.5, interval80: [1, 2], positions: [0.4, 0.4], nc: 0.2 },
    },
  };
  const driver = insightsMarkup(data, { entity: "1" });
  assert.match(driver, /Driver deep dive/);
  assert.match(driver, /position-estimate">P1 \/ P2/);
  assert.match(driver, /Average classified position <strong>P1.5/);
  assert.match(driver, /40.0% each/);
  assert.match(driver, /NC: 20.0%/);
  assert.match(driver, /class="placement-curve"/);
  assert.match(driver, /position probabilities/);
  assert.match(
    driver,
    /class="curve-point" tabindex="0" role="img" aria-label="P1: 80.0%"/,
  );
  assert.match(driver, /class="curve-tooltip"/);
  assert.doesNotMatch(driver, /insight-contenders|insight-podiums/);
  assert.equal(
    (driver.match(/<h2>Championship horizon<\/h2>/g) || []).length,
    1,
  );
  const team = insightsMarkup(data, {
    population: "constructors",
    entity: "a",
  });
  assert.match(team, /Team deep dive/);
  assert.match(team, /Team championship outlook/);
  assert.match(team, /Alpha &lt;Test&gt;/);
  assert.match(team, /detail-identity/);
  assert.doesNotMatch(team, /NaN|undefined/);
});

test("most likely result and average classified position describe different quantities", () => {
  const data = publication();
  data.insights.rounds[0].drivers["1"].win = 0.481;
  data.insights.rounds[0].placements = {
    1: { R: { mean: 2, positions: [0.481, 0.238, 0.081, 0.2], nc: 0 } },
  };
  const html = insightsMarkup(data, { entity: "1" });
  assert.match(
    html,
    /Most likely result<\/span><strong class="position-estimate">P1<\/strong><small>48.1%/,
  );
  assert.match(html, /Average classified position <strong>P2.0/);
  data.insights.rounds[0].placements["1"].R = {
    mean: 1.667,
    positions: [0.1, 0.2],
    nc: 0.7,
  };
  assert.match(
    insightsMarkup(data),
    /position-estimate">NC<\/strong><small>70.0%/,
  );
});

test("Fantasy graphics preserve negative session components and keep F1 projections separate", () => {
  const data = publication();
  data.rounds[0].forecasts["1"] = [-8, 0, 12];
  data.insights.rounds[0].drivers["1"].podium = 0.6;
  const html = insightsMarkup(data);
  assert.match(html, /Q -8.0/);
  assert.match(html, /R 12.0/);
  assert.match(html, /4.0 <small>pts/);
  assert.match(html, /signed-negative/);
  assert.match(html, /signed-negative" style="flex:0 0 40%/);
  assert.match(html, /60.0%/);
  assert.match(html, /<dt>Scored<\/dt><dd>25.0/);
  assert.match(html, /<dt>Expected gain<\/dt><dd>\+10.0/);
  assert.doesNotMatch(html, /Negative components extend left of zero/);
  assert.doesNotMatch(html, /NaN|undefined|Alpha <Test>/);
});

test("Championship horizon excludes eliminated entrants and historical records are not rendered", () => {
  const data = publication();
  const eliminated = {
    ...data.insights.championship.drivers[0],
    key: "OUT",
    name: "Eliminated racer",
    asset_id: null,
    observed: 0,
    projected: 999,
    max_final: 24,
    title_eligible: false,
  };
  data.insights.championship.drivers.unshift(eliminated);
  data.insights.history[0].drivers.push(eliminated);
  const html = insightsMarkup(data);
  assert.doesNotMatch(html, /Eliminated racer|999\.0|Historical record/);
  assert.doesNotMatch(html, /mathematically eliminated entrants hidden/);
  assert.match(html, /<dt>Maximum<\/dt><dd>50\.0/);
});

test("positive Fantasy charts start at the left instead of reserving a blank negative half", () => {
  const html = insightsMarkup(publication());
  assert.match(html, /signed-negative" style="flex:0 0 0%/);
  assert.match(html, /session-r" style="width:80%/);
});

test("racing-only deep dives and team outlook use post-round championship totals without repeated names or copy", () => {
  const data = publication();
  const html = insightsMarkup(data);
  const detail = html.slice(
    html.indexOf('<section class="panel participant-detail"'),
    html.indexOf('<section class="panel team-outlook"'),
  );
  const sidebar = detail.slice(
    detail.indexOf('<aside class="participant-prediction"'),
  );
  const catalogue = detail.slice(0, detail.indexOf("<aside"));
  assert.doesNotMatch(
    catalogue,
    /participant-tile-positions|participant-tile-metric|40.0/,
  );
  assert.match(sidebar, /40.0 pts/);
  assert.match(sidebar, /Post-race championship position<\/dt><dd>P1.4/);
  assert.match(html, /80.0 pts/);
  assert.match(html, /Post-race championship position<\/dt><dd>P2.2/);
  assert.doesNotMatch(
    detail,
    /Fantasy|View predictions|Selected|selected driver|detail-fantasy-sessions/,
  );
  assert.equal(
    (sidebar.match(/<h3>Alpha &lt;Test&gt;<\/h3>/g) || []).length,
    1,
  );
  assert.doesNotMatch(
    html,
    /Title contention|mathematically eligible contenders|Stationary-stop winner probability|Choose a participant to inspect|Position probabilities plus NC|fixed pre-weekend inputs|Not classified is a result classification/,
  );
  delete data.insights.rounds[0].championship_after;
  assert.match(
    insightsMarkup(data),
    /Post-race championship<\/dt><dd>Unavailable/,
  );
});

test("participant cards show most likely race positions and keep selection without a search", () => {
  const data = publication();
  data.assets[0].tla = "AAA";
  data.assets.push({
    id: "2",
    name: "Bravo Driver",
    kind: "DRIVER",
    team_id: "a",
    tla: "BBB",
  });
  data.rounds[0].forecasts["2"] = [4, 0, 16];
  data.insights.rounds[0].placements = {
    1: { R: { mean: 2, positions: [0.481, 0.238, 0.081, 0.2], nc: 0 } },
    2: { R: { mean: 2.1, positions: [0.1, 0.7, 0.2], nc: 0 } },
  };
  const html = insightsMarkup(data, { entity: "2" });
  assert.match(html, /participant-grid/);
  assert.match(html, /aria-label="Bravo Driver predictions"/);
  assert.match(html, /data-insight-entity="2"[^>]*aria-pressed="true"/);
  assert.doesNotMatch(html, /data-insight-entity="[12]"[^>]*hidden/);
  assert.doesNotMatch(
    html,
    /participant-search|data-participant-search|insight-participant-empty/,
  );
  assert.match(
    html,
    /participant-position" title="Most likely race result: P1 · 48.1%"><small>Likely race<\/small><strong>P1/,
  );
  assert.match(
    html,
    /participant-position" title="Most likely race result: P2 · 70.0%"><small>Likely race<\/small><strong>P2/,
  );
  assert.match(html, /position-estimate">P2<\/strong><small>70.0%/);
});
