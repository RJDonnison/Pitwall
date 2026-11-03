import test from "node:test";
import assert from "node:assert/strict";
import { scenarioPoints, seasonRange } from "../src/season-range.js";

const assets = Array.from({ length: 7 }, (_, i) => ({
  id: String(i),
  kind: i < 5 ? "DRIVER" : "CONSTRUCTOR",
}));
const drivers = new Set(assets.slice(0, 5).map((a) => a.id));
const scenario = (n) => ({
  scores: Object.fromEntries(assets.map((a) => [a.id, [0, 0, n]])),
  no_negative: Object.fromEntries(assets.map((a) => [a.id, [0, 0, n + 5]])),
});
const round = () => ({
  entries: assets.map((a) => ({ id: a.id })),
  boost: "0",
  x3: null,
  chip: null,
  points: 80,
  penalty: 0,
  joint_scenarios: [scenario(5), scenario(15)],
});

test("joint scoring includes seven selections, boost, tripling and penalties", () => {
  const r = round();
  assert.equal(scenarioPoints(r, scenario(10), drivers), 80);
  assert.equal(
    scenarioPoints(
      { ...r, chip: "x3", x3: "1", penalty: 10 },
      scenario(10),
      drivers,
    ),
    90,
  );
  for (const chip of ["wildcard", "limitless"])
    assert.equal(scenarioPoints({ ...r, chip }, scenario(10), drivers), 80);
  assert.equal(
    scenarioPoints(
      { ...r, chip: "no_negative", penalty: 10 },
      scenario(10),
      drivers,
    ),
    110,
  );
});

test("Autopilot boosts a single whole-weekend winner, including negative outcomes", () => {
  const s = scenario(-10);
  s.scores["0"] = [40, 0, -30];
  s.scores["1"] = [-20, 0, 40];
  const r = { ...round(), chip: "autopilot" };
  assert.equal(scenarioPoints(r, s, drivers), 0); // 10+20-50 +20, not sessionwise maxima
  const negative = scenario(-10);
  assert.equal(scenarioPoints(r, negative, drivers), -80);
});

test("cumulative bands retain correlated team shocks and sample later weekends independently", () => {
  const r = round();
  const result = seasonRange({ assets }, [
    r,
    { ...round(), points: 70, penalty: 10 },
  ]);
  assert.equal(result.status, "ready");
  assert.deepEqual(result.bands[0], {
    low: 40,
    high: 120,
    expected: 80,
    samples: 2,
  });
  assert.deepEqual(result.bands[1], {
    low: 70,
    high: 230,
    expected: 150,
    samples: 2,
  });
  assert.deepEqual(
    result,
    seasonRange({ assets }, [r, { ...round(), points: 70, penalty: 10 }]),
  );
  const unchanged = structuredClone(r);
  assert.deepEqual(seasonRange({ assets }, [r]).bands[0], result.bands[0]);
  assert.deepEqual(r, unchanged);
  const four = seasonRange({ assets }, Array.from({ length: 4 }, round))
    .bands[3];
  assert.equal(four.low, 240);
  assert.equal(four.high, 400);
  // Opposing driver and constructor shocks cancel in their joint sample.
  const balanced = [scenario(10), scenario(10)];
  balanced[0].scores["0"][2] += 10;
  balanced[0].scores["5"][2] -= 20;
  balanced[1].scores["0"][2] -= 10;
  balanced[1].scores["5"][2] += 20;
  assert.equal(
    seasonRange({ assets }, [{ ...r, joint_scenarios: balanced }]).bands[0].low,
    80,
  );
  assert.equal(
    seasonRange({ assets }, [{ ...r, joint_scenarios: balanced }]).bands[0]
      .high,
    80,
  );
});

test("missing constructor, chip, or complete joint history never invents a range", () => {
  for (const change of [
    (r) => delete r.joint_scenarios,
    (r) => r.joint_scenarios.pop(),
    (r) => delete r.joint_scenarios[0].scores["6"],
    (r) => (r.joint_scenarios[1].scores["1"][2] = NaN),
    (r) => {
      r.chip = "no_negative";
      delete r.joint_scenarios[0].no_negative;
    },
  ]) {
    const r = round();
    change(r);
    assert.equal(seasonRange({ assets }, [r]).status, "unavailable");
  }
});
