import test from "node:test";
import assert from "node:assert/strict";
import {
  loadParticipantMedia,
  portrait,
  creditsMarkup,
} from "../src/visuals.js";
import media from "../src/media.json" with { type: "json" };

const hirakawa = {
  id: "hirakawa",
  kind: "DRIVER",
  name: "Ryo Hirakawa",
  tla: "HIR",
  team_id: "haas",
};
const haas = {
  id: "new-haas",
  kind: "CONSTRUCTOR",
  name: "Haas F1 Team",
  team_id: "haas",
};
const asset = (file, extra = {}) => ({
  team: "Haas F1 Team",
  file,
  source: "https://media.formula1.com/image/upload/hirakawa.webp",
  width: 128,
  height: 128,
  ...extra,
});
const collection = () => ({
  headshots: [],
  drivers: [asset("drivers/Haas F1 Team/HIR.webp", { driver: "HIR" })],
  cars: [asset("cars/Haas F1 Team.webp")],
});
const response = (manifest) => async () => ({
  ok: true,
  json: async () => manifest,
});

test("Ryo Hirakawa and a new constructor ID discover real images without a static ID mapping", async () => {
  let requests = 0;
  await loadParticipantMedia(
    { assets: [hirakawa, haas] },
    async (url, options) => {
      requests++;
      assert.equal(
        url,
        "https://raw.githubusercontent.com/TracingInsights/2026/main/images/manifest.json",
      );
      assert.equal(options.cache, "no-cache");
      return { ok: true, json: async () => collection() };
    },
  );
  assert.equal(requests, 1);
  assert.match(portrait(hirakawa), /drivers\/Haas%20F1%20Team\/HIR.webp/);
  assert.match(portrait(hirakawa), /Ryo Hirakawa · 2026 portrait/);
  assert.match(portrait(haas), /cars\/Haas%20F1%20Team.webp/);
  assert.match(portrait(haas), /car-photo/);
  assert.match(creditsMarkup(), /Ryo Hirakawa/);
  assert.match(
    creditsMarkup(),
    /blob\/main\/images\/drivers\/Haas%20F1%20Team\/HIR.webp/,
  );
  assert.match(creditsMarkup(), /Source collection/);
});

test("headshots are preferred and another team's same-TLA image is never substituted", async () => {
  const manifest = collection();
  manifest.headshots.push(
    asset("headshots/Alpine/HIR.png", { team: "Alpine", driver: "HIR" }),
  );
  manifest.drivers[0].height = 3840;
  manifest.drivers[0].width = 1336;
  await loadParticipantMedia({ assets: [hirakawa, haas] }, response(manifest));
  assert.match(portrait(hirakawa), /drivers\/Haas%20F1%20Team\/HIR.webp/);
  assert.match(portrait(hirakawa), /driver-cutout/);
  manifest.headshots.push(
    asset("headshots/Haas F1 Team/HIR.png", { driver: "HIR" }),
  );
  await loadParticipantMedia({ assets: [hirakawa, haas] }, response(manifest));
  assert.match(portrait(hirakawa), /headshots\/Haas%20F1%20Team\/HIR.png/);
  assert.doesNotMatch(portrait(hirakawa), /driver-cutout/);
  manifest.headshots.pop();
  manifest.drivers = [];
  await loadParticipantMedia({ assets: [hirakawa, haas] }, response(manifest));
  assert.equal(
    portrait(hirakawa, "no matching portrait"),
    "no matching portrait",
  );
});

test("bundled matching portraits remain local, while reused IDs and team changes are re-matched", async () => {
  const ocon = { ...hirakawa, id: "118", name: "Esteban Ocon", tla: "OCO" };
  const manifest = collection();
  manifest.headshots.push(
    asset("headshots/Haas F1 Team/OCO.png", {
      driver: "OCO",
      source: media["118"].source,
    }),
  );
  await loadParticipantMedia({ assets: [ocon, haas] }, response(manifest));
  assert.match(portrait(ocon), /src="\.\/media\/118.webp\?v=/);
  const replacement = { ...hirakawa, id: "118" };
  await loadParticipantMedia(
    { assets: [replacement, haas] },
    response(manifest),
  );
  assert.match(portrait(replacement), /HIR.webp/);
  assert.doesNotMatch(portrait(replacement), /media\/118.webp/);
  const alpine = { ...haas, name: "Alpine" };
  await loadParticipantMedia({ assets: [ocon, alpine] }, response(manifest));
  assert.equal(
    portrait(ocon, "no current-team image"),
    "no current-team image",
  );
});

test("missing, ambiguous, unsafe or unavailable images retain a safe fallback", async () => {
  for (const mutate of [
    (m) => m.drivers.push({ ...m.drivers[0] }),
    (m) => (m.drivers[0].file = "drivers/../HIR.webp"),
    (m) => (m.drivers[0].source = "javascript:alert(1)"),
  ]) {
    const manifest = collection();
    mutate(manifest);
    await loadParticipantMedia(
      { assets: [hirakawa, haas] },
      response(manifest),
    );
    assert.equal(portrait(hirakawa, "fallback"), "fallback");
  }
  for (const fetcher of [
    async () => {
      throw new Error("offline");
    },
    async () => ({ ok: false }),
    response({}),
  ]) {
    await loadParticipantMedia({ assets: [hirakawa, haas] }, fetcher);
    assert.equal(portrait(hirakawa, "fallback"), "fallback");
  }
  const name = { ...hirakawa, name: 'Ryo "<Hirakawa>"' };
  await loadParticipantMedia({ assets: [name, haas] }, response(collection()));
  assert.doesNotMatch(
    portrait(name, '<svg title="fallback"></svg>'),
    /<Hirakawa>|data-portrait-fallback="<svg/,
  );
  assert.match(portrait(name), /&quot;&lt;Hirakawa&gt;&quot;/);
});

test("a late manifest response cannot overwrite images for a newer roster", async () => {
  let finish;
  const old = loadParticipantMedia(
    { assets: [hirakawa, haas] },
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const current = { ...hirakawa, id: "new-hirakawa" };
  await loadParticipantMedia(
    { assets: [current, haas] },
    response(collection()),
  );
  finish({ ok: true, json: async () => collection() });
  assert.equal(await old, false);
  assert.match(portrait(current), /HIR.webp/);
  assert.equal(portrait(hirakawa, "old roster"), "old roster");
});
