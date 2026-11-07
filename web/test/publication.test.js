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
      // The official game locks a weekend once it has started.
      locked: days < 0,
      first_session_utc: new Date(now + days * 86400000).toISOString(),
      // A weekend lasts two days: a round that started one day ago is still on.
      last_session_utc: new Date(now + (days + 2) * 86400000).toISOString(),
      forecasts: Object.fromEntries(assets.map((a) => [a.id, [1, 0, 2]])),
    })),
  };
}

const rounds = (data) => data.rounds.map((r) => r.round);

test("a started round that is not the weekend in progress is dropped instead of failing", () => {
  const data = prepare(
    forecast({
      generatedAgo: 30 * HOUR,
      state: { mode: "carried_forward", state: "paused", weekend: "Mexico" },
    }),
  );
  assert.deepEqual(rounds(data), [2, 3]);
});

test("a paused weekend stays the first round until its race has finished", () => {
  const data = prepare(
    forecast({
      generatedAgo: 30 * HOUR,
      state: {
        mode: "carried_forward",
        state: "paused",
        round: 1,
        weekend: "Race 1",
      },
    }),
  );
  assert.deepEqual(rounds(data), [1, 2, 3]);
  assert.equal(data.rounds[0].locked, true);
});

test("the paused weekend is dropped once its last session has finished", () => {
  const data = prepare(
    forecast({
      generatedAgo: 30 * HOUR,
      rounds: [-4, 5, 12], // round 1 ended two days ago
      state: {
        mode: "carried_forward",
        state: "paused",
        round: 1,
        weekend: "Race 1",
      },
    }),
  );
  assert.deepEqual(rounds(data), [2, 3]);
});

test("only the round the publisher names is kept, not any started round", () => {
  const data = prepare(
    forecast({
      generatedAgo: 30 * HOUR,
      state: {
        mode: "carried_forward",
        state: "paused",
        round: 2,
        weekend: "Race 2",
      },
    }),
  );
  assert.deepEqual(rounds(data), [2, 3]);
});

test("a cached or stale copy keeps the weekend in progress too", () => {
  for (const mode of ["cached", "stale"]) {
    const data = prepare(
      forecast({
        generatedAgo: 30 * HOUR,
        state: { mode, state: "paused", round: 1, weekend: "Race 1" },
      }),
    );
    assert.deepEqual(rounds(data), [1, 2, 3], mode);
  }
});

test("a live practice forecast for the weekend in progress is accepted", () => {
  const data = prepare(
    forecast({
      state: {
        mode: "live",
        state: "practice",
        round: 1,
        weekend: "Race 1",
      },
    }),
  );
  assert.deepEqual(rounds(data), [1, 2, 3]);
});

test("strict validation still rejects every later round that has started", () => {
  assert.throws(
    () =>
      prepare(
        forecast({
          rounds: [-1, -0.5, 5],
          state: { mode: "live", state: "practice", round: 1 },
        }),
      ),
    /started, locked or inconsistent/,
  );
});

test("a live forecast is rejected if the weekend in progress has already finished", () => {
  assert.throws(
    () =>
      prepare(
        forecast({
          rounds: [-4, 5, 12],
          state: { mode: "live", state: "paused", round: 1 },
        }),
      ),
    /started, locked or inconsistent/,
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
    () =>
      prepare({ schema_version: 1, status: "unavailable", message: "down" }),
    /down/,
  );
});

test("banner text names the state and the real last-updated time", () => {
  const base = forecast({ rounds: [3] });
  const paused = {
    ...base,
    publication_state: {
      mode: "carried_forward",
      state: "paused",
      weekend: "Mexico City",
    },
  };
  assert.match(
    bannerText(paused),
    /paused for Mexico City.*resume after the race.*Last updated/,
  );
  assert.match(
    bannerText({
      ...base,
      publication_state: { mode: "carried_forward", state: "open" },
    }),
    /last published forecasts/,
  );
  assert.match(
    bannerText({
      ...base,
      publication_state: {
        mode: "live",
        state: "practice",
        practice_sessions: ["Practice 1"],
      },
    }),
    /after each practice session.*Practice 1/,
  );
  assert.equal(
    bannerText({ ...base, publication_state: { mode: "live", state: "open" } }),
    "",
  );
  assert.equal(bannerText(base), "");
});
