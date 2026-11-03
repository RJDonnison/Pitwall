import test from "node:test";
import assert from "node:assert/strict";
import { rollBudget } from "../src/team-progress.js";

const assets = (prices, gameday) => ({
  price_gameday_id: gameday,
  assets: Object.entries(prices).map(([id, price]) => ({
    id,
    kind: id.startsWith("c") ? "CONSTRUCTOR" : "DRIVER",
    price_tenths_m: price,
  })),
});
const base = { d1: 300, d2: 250, d3: 200, d4: 150, d5: 100, c1: 280, c2: 160 };
const team = () => ({
  selected: Object.keys(base),
  budget: 1500, // value 1440 + 60 cash
  active: "",
  initial: false,
});

test("the first measurement records cash and leaves the budget alone", () => {
  const r = rollBudget(assets(base, 19), team());
  assert.equal(r.team.budget, 1500);
  assert.deepEqual(r.team.valued, { gameday: 19, cash: 60, value: 1440 });
  assert.equal(r.change, null);
});

test("a later gameday sets budget to the new team value plus the old excess cash", () => {
  const measured = rollBudget(assets(base, 19), team()).team;
  const repriced = { ...base, d1: 310, d2: 240, c1: 300 }; // value 1440 -> 1460
  const r = rollBudget(assets(repriced, 20), measured);
  assert.equal(r.team.budget, 1460 + 60);
  assert.equal(r.team.valued.gameday, 20);
  assert.deepEqual(r.team.budgetUpdate, {
    gameday: 20,
    valueFrom: 1440,
    valueTo: 1460,
    cash: 60,
    budgetFrom: 1500,
    budgetTo: 1520,
  });
});

test("falling prices lower the budget but never touch the cash", () => {
  const measured = rollBudget(assets(base, 19), team()).team;
  const r = rollBudget(assets({ ...base, d1: 250, c1: 250 }, 20), measured);
  assert.equal(r.team.budget, 1440 - 80 + 60);
  assert.equal(r.team.valued.cash, 60);
});

test("the same gameday never changes the budget and re-measures after manual edits", () => {
  let t = rollBudget(assets(base, 19), team()).team;
  t = { ...t, budget: 1600 }; // the user types a new budget
  t = rollBudget(assets(base, 19), t).team;
  assert.equal(t.budget, 1600);
  assert.equal(t.valued.cash, 160);
  // the next weekend keeps the edited excess
  const r = rollBudget(assets({ ...base, d1: 320 }, 20), t);
  assert.equal(r.team.budget, 1460 + 160);
});

test("a roster swap after measuring is re-measured, not rolled", () => {
  let t = rollBudget(assets(base, 19), team()).team;
  const withSwap = { ...base, d6: 120 };
  delete withSwap.d5;
  t = { ...t, selected: Object.keys(withSwap) };
  const r = rollBudget(assets(withSwap, 19), t);
  assert.equal(r.team.budget, 1500);
  assert.equal(r.team.valued.cash, 1500 - (1440 - 100 + 120));
});

test("teams that cannot be valued are left untouched", () => {
  const incomplete = { ...team(), selected: ["d1"] };
  assert.equal(rollBudget(assets(base, 19), incomplete).team, incomplete);
  const unknown = { ...team(), selected: ["d1", "d2", "d3", "d4", "d5", "c1", "x"] };
  assert.equal(rollBudget(assets(base, 19), unknown).team, unknown);
  const limitless = { ...team(), active: "limitless" };
  assert.equal(rollBudget(assets(base, 19), limitless).team, limitless);
  const initial = { ...team(), initial: true };
  assert.equal(rollBudget(assets(base, 19), initial).team, initial);
  const over = { ...team(), budget: 1000 }; // value above budget: invalid, untouched
  assert.equal(rollBudget(assets(base, 19), over).team, over);
});
