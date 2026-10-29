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

const highs = await loadHighs();
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
    execFileSync(executable, ["-c", script], {
      input: JSON.stringify([data, team]),
      encoding: "utf8",
    }),
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
