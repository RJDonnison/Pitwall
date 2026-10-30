import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import loadHighs from "highs";
import {
  optimize,
  validateDataset,
  validateTeam,
  total,
} from "../src/optimizer.js";
import { verifyLive } from "../src/data.js";
import { suggestionRequest } from "../src/team-suggestion.js";

const highs = await loadHighs();
test("Suggest team fills an empty slot with a capped optimized roster and normal 2× Boost", () => {
  const { data, team } = fixture();
  team.selected = [];
  team.chips = ["x3", "wildcard"];
  const original = structuredClone(team);
  const request = suggestionRequest(data, team);
  const result = optimize(highs, request.dataset, request.team);
  assert.equal(result.rounds.length, 1);
  assert.equal(result.rounds[0].entries.length, 7);
  assert.equal(result.rounds[0].cost, 350);
  assert.equal(result.rounds[0].points, 131);
  assert.equal(result.rounds[0].penalty, 0);
  assert.equal(result.rounds[0].chip, null);
  assert.deepEqual(result.rounds[0].entries.map((e) => e.id).sort(), [
    "0",
    "1",
    "2",
    "3",
    "4",
    "c0",
    "c1",
  ]);
  assert.deepEqual(team, original);
  assert.equal(data.rounds.length, 2);
});

test("Suggest team handles partial rosters but fails for unaffordable or stale data", () => {
  const { data, team } = fixture();
  team.selected = ["5"];
  assert.equal(suggestionRequest(data, team).team.selected.length, 7);
  team.budget = 349;
  assert.throws(() => suggestionRequest(data, team), /budget/);
  team.budget = 400;
  data.generated_at = new Date(Date.now() - 7 * 3600000).toISOString();
  assert.throws(() => suggestionRequest(data, team), /six hours/);
});
function fixture() {
  const assets = [
    ...Array.from({ length: 6 }, (_, i) => ({
      id: String(i),
      name: `Driver ${i}`,
      kind: "DRIVER",
      price_tenths_m: 50,
      team_id: String(Math.floor(i / 2)),
    })),
    ...Array.from({ length: 3 }, (_, i) => ({
      id: `c${i}`,
      name: `Constructor ${i}`,
      kind: "CONSTRUCTOR",
      price_tenths_m: 50,
      team_id: String(i),
    })),
  ];
  const data = {
    schema_version: 1,
    status: "ready",
    season: 2099,
    generated_at: new Date().toISOString(),
    assets,
    rounds: [0, 1].map((t) => ({
      season: 2099,
      round: t + 2,
      gameday_id: t + 2,
      name: `Race ${t + 2}`,
      sprint: t === 1,
      locked: false,
      first_session_utc: new Date(
        Date.now() + (t + 1) * 86400000,
      ).toISOString(),
      forecasts: Object.fromEntries(
        assets.map((a, i) => [
          a.id,
          [
            i,
            t ? i * 2 : 0,
            [20, 18, 12, 11, 5, 0, 14, 8, 4][i] * (t ? 0.5 : 1),
          ],
        ]),
      ),
      no_negative: Object.fromEntries(
        assets.map((a) => [a.id, [1, t ? 2 : 0, 3]]),
      ),
    })),
  };
  data.rounds.forEach((r) => {
    r.autopilot = [-1, 1].map((sign) =>
      Object.fromEntries(
        assets
          .filter((a) => a.kind === "DRIVER")
          .map((a, i) => [
            a.id,
            r.forecasts[a.id].map((v, k) => v + (k === 2 ? sign * (i + 1) : 0)),
          ]),
      ),
    );
  });
  const team = {
    selected: ["0", "1", "2", "3", "4", "c0", "c1"],
    budget: 400,
    carry: 0,
    chips: [],
    completed: true,
    initial: false,
    allowPenalties: false,
    active: "",
    restore: [],
  };
  return { data, team };
}

function python(data, team) {
  const executable =
    process.env.PYTHON ||
    (existsSync("../.venv/bin/python") ? "../.venv/bin/python" : "python3");
  const script = `import json,sys\nfrom datetime import datetime\nfrom f1fantasy.data import Asset,Weekend\nfrom f1fantasy.projections import Estimate\nfrom f1fantasy.chips import ChipValues\nfrom f1fantasy.optimizer import optimize\nd,t=json.load(sys.stdin)\na=tuple(Asset(x['id'],x['name'],x['kind'],x['team_id'],x['price_tenths_m']) for x in d['assets'])\nw=[Weekend(x['season'],x['round'],x['name'],x['gameday_id'],datetime.fromisoformat(x['first_session_utc'].replace('Z','+00:00')),x['sprint'],False) for x in d['rounds']]\ne={(i,k):Estimate(*v) for i,r in enumerate(d['rounds']) for k,v in r['forecasts'].items()}\nn={(i,k):Estimate(*v) for i,r in enumerate(d['rounds']) for k,v in r['no_negative'].items()}\np={i:tuple({k:Estimate(*v) for k,v in s.items()} for s in r['autopilot']) for i,r in enumerate(d['rounds'])}\nelig={i:frozenset(c for c in t['chips'] if c not in ('wildcard','limitless') or i>0 or t['completed']) for i in range(len(w))}\nr=optimize(a,w,e,t['budget'],None if t['initial'] else frozenset(t['selected']),t['carry'],t['allowPenalties'],available_chips=frozenset(t['chips']),chip_values=ChipValues(n,p),eligible_chips=elig,active_chip=t['active'] or None,limitless_restore=frozenset(t['restore'] or t['selected']))\nprint(json.dumps({'points':sum(x.expected_points for x in r),'rounds':[{'points':x.expected_points,'penalty':x.transfer_penalty,'chip':x.chip} for x in r]}))`;
  return JSON.parse(
    execFileSync(
      executable,
      [
        "-c",
        script.replace(
          "limitless_restore=",
          "limitless_followup=t.get('limitlessFollowup',False),limitless_restore=",
        ),
      ],
      {
        input: JSON.stringify([data, team]),
        encoding: "utf8",
      },
    ),
  );
}

for (const chip of [
  null,
  "x3",
  "autopilot",
  "no_negative",
  "wildcard",
  "limitless",
])
  test(`browser MILP matches Python objective with ${chip || "no chip"}`, () => {
    const { data, team } = fixture();
    if (chip) team.chips = [chip];
    if (chip === "wildcard" || chip === "limitless") team.active = chip;
    if (chip === "limitless") {
      team.restore = [...team.selected];
      data.assets[5].price_tenths_m = 900;
      data.rounds[0].forecasts["5"][2] = 150;
      data.rounds[0].autopilot.forEach((s) => (s["5"][2] = 150));
    }
    const result = optimize(highs, data, team),
      reference = python(data, team);
    assert.ok(Math.abs(result.points - reference.points) < 1e-5);
    for (const r of result.rounds) {
      assert.equal(r.entries.length, 7);
      assert.equal(
        r.entries.filter(
          (e) => data.assets.find((a) => a.id === e.id).kind === "DRIVER",
        ).length,
        5,
      );
      assert.ok(Math.abs(total(r.sessions) - r.penalty - r.points) < 1e-6);
    }
  });

test("custom post-Limitless transfers match Python, exceed two swaps and retain the budget cap", () => {
  const { data, team } = fixture();
  data.assets = [
    ...Array.from({ length: 8 }, (_, i) => ({
      id: String(i),
      name: `Driver ${i}`,
      kind: "DRIVER",
      team_id: `t${i % 4}`,
      price_tenths_m: 50,
    })),
    ...Array.from({ length: 4 }, (_, i) => ({
      id: `c${i}`,
      name: `Team ${i}`,
      kind: "CONSTRUCTOR",
      team_id: `t${i}`,
      price_tenths_m: 50,
    })),
  ];
  team.budget = 350;
  team.active = "limitless";
  team.chips = ["limitless"];
  team.restore = [...team.selected];
  data.rounds.forEach((r, t) => {
    r.sprint = false;
    r.forecasts = Object.fromEntries(
      data.assets.map((a) => [
        a.id,
        [
          0,
          0,
          team.selected.includes(a.id) === (t === 0) ? (t ? 1000 : 100) : 0,
        ],
      ]),
    );
    r.no_negative = {};
    r.autopilot = [];
  });
  for (const custom of [false, true]) {
    team.limitlessFollowup = custom;
    const result = optimize(highs, data, team),
      reference = python(data, team);
    assert.ok(Math.abs(result.points - reference.points) < 1e-5);
    assert.equal(result.rounds[1].transfers, custom ? 5 : 2);
    assert.equal(result.rounds[1].penalty, 0);
    assert.ok(result.rounds[1].cost <= team.budget);
  }
});

test("saves x3 for a valuable late round and selects distinct multipliers", () => {
  const { data, team } = fixture();
  team.chips = ["x3"];
  data.rounds[1].forecasts["5"] = [0, 100, 500];
  const r = optimize(highs, data, team);
  assert.equal(r.rounds[0].chip, null);
  assert.equal(r.rounds[1].chip, "x3");
  assert.equal(r.rounds[1].x3, "5");
  assert.notEqual(r.rounds[1].boost, r.rounds[1].x3);
});

test("paid net transfers and carry match Python across a full horizon", () => {
  const { data, team } = fixture();
  team.carry = 1;
  team.allowPenalties = true;
  data.rounds.push({
    ...structuredClone(data.rounds[1]),
    round: 4,
    gameday_id: 4,
    first_session_utc: new Date(Date.now() + 3 * 86400000).toISOString(),
  });
  data.rounds[1].forecasts["5"] = [0, 100, 500];
  assert.ok(
    Math.abs(optimize(highs, data, team).points - python(data, team).points) <
      1e-5,
  );
});

test("No Negative uses category uplift even when the original session is positive", () => {
  const { data, team } = fixture();
  team.active = "no_negative";
  const r = optimize(highs, data, team).rounds[0];
  assert.equal(r.chip, "no_negative");
  for (const e of r.entries) assert.ok(e.extra[0] >= 1);
});

test("active Autopilot and x3 persist without remaining inventory", () => {
  for (const chip of ["x3", "autopilot"]) {
    const { data, team } = fixture();
    team.active = chip;
    assert.equal(optimize(highs, data, team).rounds[0].chip, chip);
  }
});

test("Autopilot selects one whole-weekend winner per joint scenario", () => {
  const { data, team } = fixture();
  team.active = "autopilot";
  data.rounds[0].autopilot[0]["0"] = [40, 0, -10];
  data.rounds[0].autopilot[1]["0"] = [-40, 0, 50];
  data.rounds[0].forecasts["0"] = [0, 0, 20];
  const r = optimize(highs, data, team);
  assert.ok(Math.abs(r.points - python(data, team).points) < 1e-5);
});

test("active Wildcard gives the same capped one-round optimum for different starting rosters", () => {
  const { data, team } = fixture();
  data.rounds = data.rounds.slice(0, 1);
  team.active = "wildcard";
  team.chips = ["wildcard"];
  team.budget = 350;
  const first = optimize(highs, data, team);
  const second = optimize(highs, data, {
    ...team,
    selected: ["1", "2", "3", "4", "5", "c1", "c2"],
  });
  assert.equal(first.points, second.points);
  assert.deepEqual(
    first.rounds[0].entries.map((e) => e.id).sort(),
    second.rounds[0].entries.map((e) => e.id).sort(),
  );
  assert.equal(first.rounds[0].penalty, 0);
  assert.equal(second.rounds[0].penalty, 0);
  assert.notEqual(first.rounds[0].transfers, second.rounds[0].transfers);
});

test("Wildcard still respects budget and remaining chips rather than equating different profiles", () => {
  const { data, team } = fixture();
  data.assets[0].price_tenths_m = 150;
  team.selected = ["1", "2", "3", "4", "5", "c1", "c2"];
  team.active = "wildcard";
  team.chips = ["wildcard"];
  team.budget = 350;
  const capped = optimize(highs, data, team);
  const richer = optimize(highs, data, { ...team, budget: 450 });
  assert.ok(richer.points > capped.points);
  const extraChip = optimize(highs, data, {
    ...team,
    chips: ["wildcard", "no_negative"],
  });
  assert.ok(extraChip.points > capped.points);
  assert.equal(extraChip.rounds[0].chip, "wildcard");
  assert.equal(extraChip.rounds[1].chip, "no_negative");
});

test("Autopilot total includes exactly one extra copy of the best whole-weekend driver in each scenario", () => {
  const { data, team } = fixture();
  data.rounds = [data.rounds[1]];
  team.active = "autopilot";
  const round = data.rounds[0];
  for (const a of data.assets) {
    round.forecasts[a.id] = a.kind === "DRIVER" ? [1, 0, 1] : [0, 0, 0];
    if (a.kind === "DRIVER")
      round.autopilot.forEach((s) => (s[a.id] = [1, 0, 1]));
  }
  round.autopilot[0]["0"] = [10, 0, 30];
  round.autopilot[1]["0"] = [0, 20, 0];
  round.forecasts["0"] = [5, 10, 15];
  round.autopilot[0]["1"] = [0, 0, 10];
  round.autopilot[1]["1"] = [10, 0, 50];
  round.forecasts["1"] = [5, 0, 30];
  round.forecasts.c0 = [3, 0, 4];
  round.forecasts.c1 = [1, 0, 2];
  const result = optimize(highs, data, team);
  const r = result.rounds[0];
  // Unboosted team = 81. Winners score 40 and 60: mean extra = 50.
  // Highest mean driver alone scores 35; choosing that driver in advance is 116.
  assert.equal(r.points, 131);
  assert.equal(result.points, 131);
  assert.deepEqual(r.sessions, [27, 10, 94]);
  assert.equal(total(r.entries.map((e) => total(e.base))), 81);
  assert.equal(total(r.entries.map((e) => total(e.extra))), 50);
  assert.deepEqual(r.entries.find((e) => e.id === "0").extra, [5, 0, 15]);
  assert.deepEqual(r.entries.find((e) => e.id === "1").extra, [5, 0, 25]);
  assert.equal(r.entries.find((e) => e.id === "c0").points, 7);
  assert.equal(r.entries.find((e) => e.id === "c1").points, 3);
});

test("missing chip evidence, invalid teams and unknown restoration fail", () => {
  const { data, team } = fixture();
  team.active = "limitless";
  assert.throws(() => validateTeam(data, team), /restore/);
  team.active = "";
  team.chips = ["autopilot"];
  data.rounds[0].autopilot = [];
  assert.throws(() => optimize(highs, data, team), /scenarios/);
  team.selected.pop();
  assert.throws(() => validateTeam(data, team), /five drivers/);
});

test("stale, started, malformed and unavailable data cannot yield a plan", () => {
  for (const mutate of [
    (d) => (d.generated_at = new Date(Date.now() - 7 * 3600000).toISOString()),
    (d) =>
      (d.rounds[0].first_session_utc = new Date(Date.now() - 1).toISOString()),
    (d) => (d.rounds[0].forecasts["0"][0] = NaN),
    (d) => (d.status = "unavailable"),
    (d) => d.assets.push(d.assets[0]),
  ]) {
    const { data } = fixture();
    mutate(data);
    assert.throws(() => validateDataset(data));
  }
});

test("CORS failure is explicitly unverified, not a claim of live prices", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => {
      throw new TypeError("CORS");
    };
    assert.equal((await verifyLive(fixture().data)).verified, false);
  } finally {
    globalThis.fetch = original;
  }
});

test("readable official feeds must match finite prices and an unlocked event", async () => {
  const original = globalThis.fetch;
  const { data } = fixture();
  data.price_gameday_id = data.rounds[0].gameday_id;
  const roster = {
    Value: data.assets.map((a) => ({
      IsActive: 1,
      PlayerId: a.id,
      PositionName: a.kind,
      Value: a.price_tenths_m / 10,
    })),
  };
  const statistics = {
    season: data.season,
    ...Object.fromEntries(
      ["driver", "constructor"].map((kind) => [
        kind,
        [
          {
            config: { key: "fPoints" },
            participants: data.assets
              .filter((a) => a.kind === kind.toUpperCase())
              .map((a) => ({
                playerid: a.id,
                curvalue: a.price_tenths_m / 10,
              })),
          },
        ],
      ]),
    ),
  };
  const schedule = {
    fixtures: [
      {
        Season: data.season,
        GamedayId: data.price_gameday_id,
        IsPostponed: 0,
        GDIsLocked: 0,
        MDIsLocked: 0,
        MHIsLocked: 0,
      },
    ],
  };
  try {
    globalThis.fetch = async (url) => ({
      ok: true,
      json: async () => ({
        Data: url.includes("driverconstructors")
          ? statistics
          : url.includes("raceday")
            ? schedule
            : roster,
      }),
    });
    assert.equal((await verifyLive(data)).verified, true);
    roster.Value[0].Value = "not-a-price";
    await assert.rejects(() => verifyLive(data), /prices differ/);
    roster.Value[0].Value = data.assets[0].price_tenths_m / 10;
    statistics.driver[0].participants[0].curvalue = "not-a-price";
    await assert.rejects(() => verifyLive(data), /prices differ/);
    statistics.driver[0].participants[0].curvalue =
      data.assets[0].price_tenths_m / 10;
    schedule.fixtures[0].GDIsLocked = 1;
    await assert.rejects(() => verifyLive(data), /locked/);
  } finally {
    globalThis.fetch = original;
  }
});
