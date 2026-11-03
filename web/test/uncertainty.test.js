import test from "node:test";
import assert from "node:assert/strict";
import { assetHalfWidth, planBands, roundHalfWidth } from "../src/uncertainty.js";

const interval = (low, high) => ({ low, high });
const round = (points, radius, boosted = false) => ({
  points,
  intervals: { a: { Q: interval(-radius, radius), R: interval(-radius, radius) } },
  entries: [{ id: "a", base: [1, 0, 1], points: boosted ? 4 : 2 }],
});

test("combines session ranges in quadrature and scales by the multiplier", () => {
  const r = round(2, 3);
  assert.ok(Math.abs(assetHalfWidth(r, "a") - Math.sqrt(18)) < 1e-9);
  assert.ok(Math.abs(roundHalfWidth(round(4, 3, true)) - 2 * Math.sqrt(18)) < 1e-9);
});

test("cumulative bands widen with each round and stop at a missing range", () => {
  const rounds = [round(10, 3), round(10, 3), { ...round(10, 3), intervals: {} }];
  const bands = planBands(rounds);
  assert.ok(Math.abs(bands[0].high - bands[0].low - 2 * Math.sqrt(18)) < 1e-9);
  assert.ok(bands[1].high - bands[1].low > bands[0].high - bands[0].low);
  assert.equal(bands[1].low + bands[1].high, 40);
  assert.equal(bands[2], null);
});
