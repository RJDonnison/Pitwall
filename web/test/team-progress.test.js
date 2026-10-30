import test from "node:test";
import assert from "node:assert/strict";
import {
  rememberWeekend,
  weekendReady,
  adoptWeekend,
} from "../src/team-progress.js";

const now = Date.parse("2030-02-01T12:00:00Z");
function fixture(chip = "x3") {
  const assets = [
    ...Array.from({ length: 6 }, (_, i) => ({
      id: String(i),
      name: `Driver ${i}`,
      kind: "DRIVER",
      price_tenths_m: 50,
    })),
    ...["c0", "c1"].map((id) => ({
      id,
      name: id,
      kind: "CONSTRUCTOR",
      price_tenths_m: 50,
    })),
  ];
  const selected = ["0", "1", "2", "3", "4", "c0", "c1"];
  const team = {
    name: "Only this profile",
    season: 2030,
    selected,
    budget: 400,
    carry: 0,
    chips: ["x3", "limitless", "wildcard"],
    initial: false,
    completed: true,
    active: "",
    restore: [],
    allowPenalties: true,
  };
  const old = {
    season: 2030,
    assets,
    rounds: [
      {
        gameday_id: 2,
        round: 2,
        name: "Previous Grand Prix",
        last_session_utc: new Date(now - 3600000).toISOString(),
      },
    ],
  };
  const result = {
    rounds: [
      {
        gameday_id: 2,
        round: 2,
        name: "Previous Grand Prix",
        entries: ["0", "1", "2", "3", "5", "c0", "c1"].map((id) => ({ id })),
        cost: 350,
        carry: 1,
        chip,
      },
    ],
  };
  const fresh = {
    schema_version: 1,
    status: "ready",
    season: 2030,
    generated_at: new Date(now).toISOString(),
    assets: structuredClone(assets),
    rounds: [
      {
        season: 2030,
        gameday_id: 3,
        round: 3,
        name: "Next Grand Prix",
        sprint: false,
        locked: false,
        first_session_utc: new Date(now + 86400000).toISOString(),
        forecasts: Object.fromEntries(assets.map((a) => [a.id, [1, 0, 2]])),
      },
    ],
  };
  return { team, old, result, fresh };
}

test("completed suggestion survives new publications and updates only local roster, cash, carry and consumed chip", () => {
  const { team, old, result, fresh } = fixture();
  team.weekendSuggestion = rememberWeekend(old, team, result);
  const saved = JSON.parse(JSON.stringify(team));
  assert.equal(
    rememberWeekend(fresh, team, { rounds: [{ gameday_id: 3 }] }),
    team.weekendSuggestion,
  );
  fresh.assets[0].price_tenths_m = 55;
  const next = adoptWeekend(fresh, team, now);
  assert.deepEqual(next.selected, ["0", "1", "2", "3", "5", "c0", "c1"]);
  assert.equal(next.budget, 405); // Current roster value + the original 50 cash.
  assert.equal(next.carry, 1);
  assert.deepEqual(next.chips, ["limitless", "wildcard"]);
  assert.equal(next.weekendSuggestion, null);
  assert.equal(next.active, "");
  assert.deepEqual(team, saved);
});

test("Limitless adopts restored roster and resets carry rather than saving uncapped temporary picks", () => {
  const { team, old, result, fresh } = fixture("limitless");
  team.active = "limitless";
  team.restore = [...team.selected];
  team.selected = result.rounds[0].entries.map((e) => e.id);
  old.assets.find((a) => a.id === "5").price_tenths_m = 500;
  result.rounds[0].cost = 800;
  team.weekendSuggestion = rememberWeekend(old, team, result);
  const next = adoptWeekend(fresh, team, now);
  assert.deepEqual(next.selected, team.restore);
  assert.equal(next.budget, 400);
  assert.equal(next.carry, 0);
  assert.deepEqual(next.restore, []);
  assert.ok(!next.chips.includes("limitless"));
});

test("uncompleted, missing-end and wrong-season suggestions cannot be adopted", () => {
  const { team, old, result, fresh } = fixture();
  team.weekendSuggestion = rememberWeekend(old, team, result);
  for (const patch of [
    { end: new Date(now + 3600000).toISOString() },
    { end: null },
    { season: 2029 },
    { round: 3 },
  ]) {
    const t = {
      ...team,
      weekendSuggestion: { ...team.weekendSuggestion, ...patch },
    };
    assert.equal(weekendReady(fresh, t.weekendSuggestion, now), false);
    assert.throws(() => adoptWeekend(fresh, t, now), /after the weekend/);
  }
});

test("stale data, inactive selections and malformed saved budget never overwrite a profile", () => {
  const { team, old, result, fresh } = fixture();
  team.weekendSuggestion = rememberWeekend(old, team, result);
  assert.throws(
    () =>
      adoptWeekend(
        { ...fresh, generated_at: new Date(now - 7 * 3600000).toISOString() },
        team,
        now,
      ),
    /six hours/,
  );
  assert.throws(
    () =>
      adoptWeekend(
        { ...fresh, assets: fresh.assets.filter((a) => a.id !== "5") },
        team,
        now,
      ),
    /no longer active/,
  );
  assert.throws(
    () =>
      adoptWeekend(
        fresh,
        {
          ...team,
          weekendSuggestion: { ...team.weekendSuggestion, cash: NaN },
        },
        now,
      ),
    /budget/,
  );
  for (const patch of [{ selected: null }, { chip: "unknown" }]) {
    assert.throws(
      () =>
        adoptWeekend(
          fresh,
          {
            ...team,
            weekendSuggestion: { ...team.weekendSuggestion, ...patch },
          },
          now,
        ),
      /suggestion cannot be verified/,
    );
  }
});
