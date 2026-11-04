import assert from "node:assert/strict";
import test from "node:test";
import {
  extractSectors,
  sectorMarkup,
  circuitMapEvent,
} from "../src/circuit-maps.js";
import { insightHero } from "../src/insight-visuals.js";

function pixels(colors = ["#e6007e", "#f5d526", "#4a9ed8"]) {
  const width = 1000,
    height = 500,
    data = new Uint8ClampedArray(width * height * 4);
  const rect = (left, top, right, bottom, color) => {
    const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
    for (let y = top; y <= bottom; y++)
      for (let x = left; x <= right; x++)
        data.set([...rgb, 255], (y * width + x) * 4);
  };
  colors.forEach((color, i) => {
    const y = 100 + i * 100;
    rect(96, y - 4, 904, y + 9, "#000000");
    rect(100, y, 900, y + 5, color);
    rect(430, y - 10, 500, y + 10, "#ffffff");
    rect(550, y - 10, 610, y + 10, "#ffffff");
    rect(630, y - 10, 690, y + 10, "#ffffff");
    rect(10 + i * 100, 400, 80 + i * 100, 425, color);
    rect(400, 430 + i * 10, 900, 435 + i * 10, color);
  });
  return { data, width, height };
}

test("remote map processing retains road surfaces across labels and drops legend boxes", () => {
  const sectors = extractSectors(pixels());
  assert.equal(sectors.length, 3);
  for (const sector of sectors) {
    const points = sector.flat();
    assert.equal(Math.min(...points.map((p) => p[0])), 45);
    assert.equal(Math.max(...points.map((p) => p[0])), 635);
    assert.ok(
      Math.max(...points.map((p) => p[1])) -
        Math.min(...points.map((p) => p[1])) <
        10,
    );
  }
  const markup = sectorMarkup(sectors, "New <Venue>", "New City");
  assert.match(markup, /viewBox="0 0 680 300"/);
  for (const color of ["#e7527d", "#e5bd43", "#55b9cc"])
    assert.match(markup, new RegExp(`fill="${color}"`));
  assert.match(markup, /New &lt;Venue&gt;/);
});

test("the alternative official palette keeps its sector order without invented splits", () => {
  assert.equal(
    extractSectors(pixels(["#ed1c24", "#00a6d0", "#f5d526"])).length,
    3,
  );
  assert.throws(() => extractSectors(pixels(["#e6007e"])), /unavailable/);
});

test("map geometry is reused across views and failed maps have an explicit fallback", async () => {
  const original = globalThis.document;
  let reads = 0;
  globalThis.document = {
    createElement: () => ({
      getContext: () => ({
        drawImage() {},
        getImageData() {
          reads++;
          return pixels();
        },
      }),
    }),
  };
  const image = (key) => ({
    matches: () => true,
    naturalWidth: 1000,
    naturalHeight: 500,
    parentElement: {
      dataset: { mapKey: key, mapName: "New Venue", mapLocation: "New City" },
    },
  });
  try {
    const first = image("test-map"),
      second = image("test-map");
    await Promise.all([
      circuitMapEvent({ type: "load", target: first }),
      circuitMapEvent({ type: "load", target: second }),
    ]);
    assert.equal(reads, 1);
    assert.equal(first.parentElement.outerHTML, second.parentElement.outerHTML);
    assert.match(first.parentElement.outerHTML, /sector-surface/);
    const failed = image("failed-map");
    await circuitMapEvent({ type: "error", target: failed });
    assert.match(failed.parentElement.innerHTML, /Circuit sectors unavailable/);
    assert.match(
      failed.parentElement.innerHTML,
      /Open the detailed official map/,
    );
    assert.doesNotMatch(failed.parentElement.innerHTML, /sector-surface/);
  } finally {
    globalThis.document = original;
  }
});

test("a newly published venue replaces static guides with seasonal specs and remote artwork", () => {
  const guide = {
    season: 2027,
    location: "New City",
    source: "https://www.formula1.com/en/racing/2027/new-venue",
    map_asset: "https://media.formula1.com/image/upload/2027/newdetailed.webp",
    photo_asset: "https://media.formula1.com/image/upload/2027/newhero.webp",
    description: "New layout <verified>",
    first_gp: 2027,
    lap_record: "1:20.123",
    record_driver: "New Driver",
  };
  const round = {
    name: "New Venue Grand Prix",
    circuit: guide,
    track_spec: { length_km: 5.123, race_laps: 60, race_distance_km: 307.38 },
  };
  const markup = insightHero({ season: 2027 }, round, {
    form_samples: { R: 8, S: 2 },
  });
  assert.match(markup, /New City/);
  assert.match(markup, /5.123 km/);
  assert.match(markup, /New layout &lt;verified&gt;/);
  assert.match(markup, /2027 official circuit guide/);
  assert.match(markup, /crossorigin="anonymous"/);
  assert.match(markup, /2027\/newdetailed.webp/);
  assert.match(markup, /2027\/newhero.webp/);
  assert.doesNotMatch(markup, /Circuit outline unavailable|\/media\//);
});
