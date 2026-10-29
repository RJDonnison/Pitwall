import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import {
  circuitMarkup,
  circuitForRace,
  priceTrend,
  portrait,
  creditsMarkup,
} from "../src/visuals.js";
import { heroMarkup, rosterMarkup } from "../src/views.js";
import media from "../src/media.json" with { type: "json" };

test("each remaining race has its own real projected circuit, not a reused image", () => {
  const names = [
    "Mexico City Grand Prix",
    "São Paulo Grand Prix",
    "Las Vegas Grand Prix",
    "Qatar Grand Prix",
    "Abu Dhabi Grand Prix",
  ];
  assert.equal(new Set(names.map((n) => circuitForRace(n).id)).size, 5);
  for (const name of names) {
    const html = circuitMarkup(name);
    assert.match(html, /circuit outline/);
    assert.doesNotMatch(html, /NaN|Infinity|undefined/);
  }
  assert.match(circuitMarkup("Unknown Grand Prix"), /unavailable/);
  const data = {
    rounds: names.map((name) => ({
      name,
      round: 1,
      first_session_utc: "2099-01-01T12:00:00Z",
    })),
  };
  assert.match(heroMarkup(data, {}, { selectedRound: 4 }), /ae-2009/);
  assert.match(heroMarkup(data, {}, null), /mx-1962/);
  assert.doesNotMatch(
    heroMarkup(data, {}, null),
    /not a verified Fantasy lock/,
  );
});
test("sparklines use actual recorded prices and missing history is not fabricated", () => {
  const a = { id: "a" },
    data = {
      price_history: {
        a: [
          { gameday_id: 1, price_tenths_m: 50 },
          { gameday_id: 2, price_tenths_m: 48 },
          { gameday_id: 3, price_tenths_m: 55 },
        ],
      },
    };
  assert.match(priceTrend(data, a), /\+\$0\.5m/);
  assert.match(priceTrend(data, a), /\$5\.0m, \$4\.8m, \$5\.5m/);
  assert.match(priceTrend({}, a), /unavailable/);
  assert.doesNotMatch(priceTrend({}, a), /<polyline/);
});
test("all 33 portraits are local and attributed under verified open licences", () => {
  assert.equal(Object.keys(media).length, 33);
  for (const [id, p] of Object.entries(media)) {
    assert.match(p.license, /^(CC BY-SA |CC BY |CC0)/);
    assert.match(p.license_url, /creativecommons\.org/);
    assert.match(p.source, /^https:\/\/commons\.wikimedia\.org\//);
    assert.ok(p.author && p.changes);
    assert.ok(
      existsSync(new URL("../public/" + p.path.slice(2), import.meta.url)),
    );
    assert.match(portrait({ id, kind: "DRIVER" }), /archive photograph/);
  }
  assert.match(creditsMarkup(), /MIT licence/);
});
test("Garage roster is price-focused and does not include forecast scores", () => {
  const assets = Array.from({ length: 7 }, (_, i) => ({
    id: String(i),
    name: "Asset " + i,
    kind: i < 5 ? "DRIVER" : "CONSTRUCTOR",
    team_id: "x",
    price_tenths_m: 50,
  }));
  const html = rosterMarkup(
    { assets },
    { selected: assets.map((a) => a.id) },
    {},
  );
  assert.equal((html.match(/data-remove=/g) || []).length, 7);
  assert.doesNotMatch(
    html,
    /base forecast|Projected|mini-splits|NaN|undefined/,
  );
});
