import test from "node:test";
import assert from "node:assert/strict";
import { prepare, bannerText } from "../src/publication.js";

const HOUR = 3600000;
function forecast({ generatedAgo = 0, rounds, state } = {}) {
  const now = Date.now();
  const assets = [
    ...Array.from({ length: 6 }, (_, i) => ({
      id: String(i),
      name: `Driver ${i}`,
      kind: "DRIVER",
      price_tenths_m: 50,
      team_id: String(Math.floor(i / 2)),
    })),
    ...["c0", "c1", "c2"].map((id, i) => ({
      id,
      name: id,
      kind: "CONSTRUCTOR",
      price_tenths_m: 50,
      team_id: String(i),
    })),
  ];
  return {
    schema_version: 1,
    status: "ready",
    season: 2099,
    generated_at: new Date(now - generatedAgo).toISOString(),
    assets,
    publication_state: state,
    rounds: (rounds ?? [-1, 5, 12]).map((days, t) => ({
      season: 2099,
      round: t + 1,
      name: `Race ${t + 1}`,
      sprint: false,
      locked: false,
      first_session_utc: new Date(now + days * 86400000).toISOString(),
      forecasts: Object.fromEntries(assets.map((a) => [a.id, [1, 0, 2]])),
    })),
  };
}

test("a carried-forward forecast drops the round already under way instead of failing", () => {
  const data = prepare(
    forecast({
      generatedAgo: 30 * HOUR,
      state: { mode: "carried_forward", state: "paused", weekend: "Mexico" },
    }),
  );
  assert.deepEqual(
    data.rounds.map((r) => r.round),
    [2, 3],
  );
});

test("a live forecast older than six hours is shown as stale, not rejected", () => {
  const data = prepare(forecast({ generatedAgo: 9 * HOUR, rounds: [2, 9] }));
  assert.equal(data.publication_state.mode, "stale");
  assert.equal(data.rounds.length, 2);
});

test("a fresh live forecast keeps strict validation of started rounds", () => {
  assert.throws(
    () => prepare(forecast({ state: { mode: "live" } })),
    /started, locked or inconsistent/,
  );
});

test("an unavailable publication is still an error for the caller to handle", () => {
  assert.throws(
    () => prepare({ schema_version: 1, status: "unavailable", message: "down" }),
    /down/,
  );
});

test("banner text names the state and the real last-updated time", () => {
  const base = forecast({ rounds: [3] });
  const paused = {
    ...base,
    publication_state: { mode: "carried_forward", state: "paused", weekend: "Mexico City" },
  };
  assert.match(bannerText(paused), /paused for Mexico City.*resume after the race.*Last updated/);
  assert.match(
    bannerText({ ...base, publication_state: { mode: "carried_forward", state: "open" } }),
    /last published forecasts/,
  );
  assert.match(
    bannerText({
      ...base,
      publication_state: { mode: "live", state: "practice", practice_sessions: ["Practice 1"] },
    }),
    /after each practice session.*Practice 1/,
  );
  assert.equal(bannerText({ ...base, publication_state: { mode: "live", state: "open" } }), "");
  assert.equal(bannerText(base), "");
});
