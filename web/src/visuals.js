import photos from "./media.json" with { type: "json" };
import circuits from "./circuits.json" with { type: "json" };
import racePhotos from "./race-media.json" with { type: "json" };
import trackGuides from "./track-guides.json" with { type: "json" };
import sectorMaps from "./sector-maps.json" with { type: "json" };
import { esc } from "./text.js";

export const logo = () =>
  '<svg class="pitwall-logo" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="6" fill="#1c1917"/><path d="m8 30 7-20h17l-3 8H18l-4 12Z" fill="#fbfbfa"/><path d="M20 22h10l-2 6H18Z" fill="#d94636"/></svg>';

const collection =
  "https://raw.githubusercontent.com/TracingInsights/2026/main/images/";
const repository = "https://github.com/TracingInsights/2026/blob/main/";
const identity = (value) => normalize(value || "").replace(/[^a-z0-9]/g, "");
const teamIdentity = (value) => identity(value).replace(/f1team$/, "");
const imageFile = (file) => file.split("/").map(encodeURIComponent).join("/");
let participantPhotos = photos;
let mediaAssets = null;

export async function loadParticipantMedia(dataset, fetcher = fetch) {
  const assets = dataset.assets;
  const before = JSON.stringify(participantPhotos);
  mediaAssets = assets;
  const changed = () =>
    mediaAssets === assets && JSON.stringify(participantPhotos) !== before;
  const teamName = (asset) =>
    asset.kind === "CONSTRUCTOR"
      ? asset.name
      : assets.find(
          (a) => a.kind === "CONSTRUCTOR" && a.team_id === asset.team_id,
        )?.name || asset.team_name;
  // Bind bundled images to the current identity, not just an ID that may be reused.
  participantPhotos = Object.fromEntries(
    assets.map((asset) => {
      const local = photos[asset.id];
      const path = decodeURIComponent(local?.repository || "");
      const team =
        asset.kind === "DRIVER"
          ? path.match(/images\/(?:headshots|drivers)\/([^/]+)\//)?.[1]
          : path.match(/images\/cars\/([^/]+)\.[^.]+$/)?.[1];
      return [
        asset.id,
        local &&
        identity(local.name) === identity(asset.name) &&
        (!local.repository ||
          teamIdentity(team) === teamIdentity(teamName(asset)))
          ? local
          : null,
      ];
    }),
  );
  try {
    const response = await fetcher(`${collection}manifest.json`, {
      cache: "no-cache",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return changed();
    const manifest = await response.json();
    if (
      !["headshots", "drivers", "cars"].every((key) =>
        Array.isArray(manifest[key]),
      )
    )
      return changed();
    if (mediaAssets !== assets) return false;
    const next = { ...participantPhotos };
    for (const asset of assets) {
      const driver = asset.kind === "DRIVER";
      const matches = (rows) =>
        rows.filter(
          (row) =>
            teamIdentity(row.team) === teamIdentity(teamName(asset)) &&
            (!driver || row.driver === asset.tla),
        );
      let candidates = matches(driver ? manifest.headshots : manifest.cars);
      if (driver && candidates.length === 0)
        candidates = matches(manifest.drivers);
      if (candidates.length !== 1) continue;
      const row = candidates[0];
      if (
        typeof row.file !== "string" ||
        !/^(?:headshots|drivers|cars)\//.test(row.file) ||
        row.file.split("/").some((part) => part === ".." || !part) ||
        !row.source?.startsWith("https://media.formula1.com/")
      )
        continue;
      const file = imageFile(row.file);
      const local = next[asset.id];
      if (
        local?.source === row.source &&
        local.repository?.endsWith(`/images/${file}`)
      )
        continue;
      next[asset.id] = {
        path: collection + file,
        name: asset.name,
        subject: `${asset.name} · 2026 ${driver ? "portrait" : "car"}`,
        author: "Formula 1 · distributed by TracingInsights",
        license: "Upstream repository: Apache-2.0; source imagery: Formula 1",
        license_url: repository + "LICENSE",
        source: row.source,
        repository: repository + "images/" + file,
        cutout: driver && row.height > row.width,
        changes:
          "Displayed from the upstream collection; tall driver cutouts cropped to the upper square. Not Creative Commons.",
      };
    }
    participantPhotos = next;
    return changed();
  } catch {
    return changed(); // Image discovery must not interrupt verified forecasts or planning.
  }
}

export function footerMarkup() {
  return `<footer class="site-footer"><div class="footer-principle"><h2>Think in seasons.</h2></div><div class="footer-columns"><section><div class="footer-column-heading"><h3>One joint plan</h3><span>Optimizer</span></div><p>Your team, Boost and chips, planned across the season.</p><a href="https://fantasy.formula1.com/en/game-rules" target="_blank" rel="noopener noreferrer">Fantasy rules ↗</a></section><section><div class="footer-column-heading"><h3>Forecasts</h3><span>Model</span></div><p>Past results inform estimates. Future prices use today's values. Weather is display-only.</p><a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo · CC BY 4.0 ↗</a></section><section><div class="footer-column-heading"><h3>Your teams stay here</h3><span>Privacy</span></div><p>Independent teams, stored in your browser.</p></section></div><div class="footer-status"><span class="footer-brand">${logo()}<b>Pitwall</b></span><div class="data-status"><span id="publication-status" role="status">Loading data…</span><p id="model-accuracy" class="model-accuracy"></p><p id="publication-window" class="sr-only"></p></div></div><p class="footer-disclaimer">Not affiliated with Formula 1.</p>${creditsMarkup()}</footer>`;
}
export function portrait(asset, fallback = "") {
  const photo = participantPhotos[asset.id];
  return photo
    ? `<img class="asset-photo ${asset.kind === "CONSTRUCTOR" ? "car-photo" : ""} ${photo.repository ? "official-photo" : ""} ${photo.cutout ? "driver-cutout" : ""}" src="${esc(photo.path)}${photo.revision ? `?v=${esc(photo.revision.slice(0, 12))}` : ""}" alt="${esc(photo.subject)}${photo.repository ? "" : " (archive photograph)"}" title="${esc(photo.author)} · ${esc(photo.license)} · full attribution in footer" data-portrait-fallback="${esc(fallback)}" loading="lazy" width="480" height="480"/>`
    : fallback;
}
export function creditsMarkup() {
  return `<details id="image-credits"><summary>Image & circuit credits</summary><p>Driver and car images: Formula 1, via the requested TracingInsights 2026 repository (Apache-2.0 repository licence). Source imagery is not labelled Creative Commons. Venue photographs retain their individual Commons licences. No endorsement is implied.</p><ul>${Object.values(
    { ...participantPhotos, ...racePhotos },
  )
    .filter(Boolean)
    .map(
      (p) =>
        `<li><a href="${esc(p.source)}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · ${esc(p.subject)}</a> — ${esc(p.author)} · <a href="${esc(p.license_url)}" target="_blank" rel="noopener noreferrer">${esc(p.license)}</a>${p.repository ? ` · <a href="${esc(p.repository)}" target="_blank" rel="noopener noreferrer">${p.revision ? "Pinned source" : "Source collection"}</a>` : ""}. ${esc(p.changes)}</li>`,
    )
    .join(
      "",
    )}</ul><p>Venue hero photographs and 2026 sector geometry: Formula 1 official circuit guides, checked 30 October 2026. Copyright remains with the respective rights holders; no Creative Commons licence is claimed. Clean SVG maps extract the coloured sector surfaces, bridge obscuring text-label gaps and omit annotations; full original maps remain linked.</p><ul>${Object.entries(
    trackGuides,
  )
    .map(
      ([id, g]) =>
        `<li><a href="${g.source}" target="_blank" rel="noopener noreferrer">${esc(circuits.find((c) => c.id === id)?.name || id)} · official circuit guide</a> · <a href="${g.photo_asset}" target="_blank" rel="noopener noreferrer">Original venue image</a> · <a href="${g.map_asset}" target="_blank" rel="noopener noreferrer">Original map</a>. Downloaded as WebP for local display; hero cropped with an image scrim.</li>`,
    )
    .join(
      "",
    )}</ul><p>Circuit coordinates © 2019–2025 Tomislav Bacinger, <a href="https://github.com/bacinger/f1-circuits" target="_blank" rel="noopener noreferrer">f1-circuits</a> · <a href="./media/CIRCUITS-LICENSE.txt">MIT licence</a>. Projected into illustrative SVG outlines; not live track maps. Track specifications: <a href="https://www.formula1.com/en/racing/2026" target="_blank" rel="noopener noreferrer">official Formula 1 circuit guides</a>.</p></details>`;
}
const normalize = (value) =>
  value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
export function circuitForRace(name) {
  const aliases = {
    australian: "au-1953",
    bahrain: "bh-2002",
    chinese: "cn-2004",
    japanese: "jp-1962",
    "saudi arabian": "sa-2021",
    miami: "us-2022",
    "emilia romagna": "it-1953",
    monaco: "mc-1929",
    barcelona: "es-1991",
    catalunya: "es-1991",
    spanish: "es-2026",
    canadian: "ca-1978",
    austrian: "at-1969",
    british: "gb-1948",
    belgian: "be-1925",
    hungarian: "hu-1986",
    dutch: "nl-1948",
    italian: "it-1922",
    azerbaijan: "az-2016",
    singapore: "sg-2008",
    "united states": "us-2012",
    "mexico city": "mx-1962",
    mexican: "mx-1962",
    "sao paulo": "br-1940",
    brazilian: "br-1940",
    "las vegas": "us-2023",
    qatar: "qa-2004",
    "abu dhabi": "ae-2009",
  };
  const key = Object.keys(aliases).find((key) => normalize(name).includes(key));
  return key ? circuits.find((c) => c.id === aliases[key]) : null;
}
export function circuitMarkup(name) {
  const circuit = circuitForRace(name);
  if (!circuit)
    return '<div class="circuit-missing">Circuit outline unavailable</div>';
  const map = sectorMaps[circuit.id];
  if (map) {
    const colors = ["#e7527d", "#e5bd43", "#55b9cc"];
    return `<div class="circuit-art sector-map" data-circuit="${circuit.id}"><svg viewBox="0 0 680 300" role="img" aria-label="${esc(circuit.name)} circuit sector map"><title>${esc(circuit.name)} · official sectors 1, 2 and 3</title>${map.sectors.map((paths, i) => `<path class="sector-surface" fill="${colors[i]}" stroke="${colors[i]}" fill-rule="evenodd" d="${paths.map((p) => p.map((v, j) => `${j ? "L" : "M"}${v.join(",")}`).join(" ") + " Z").join(" ")}"/>`).join("")}</svg><div class="sector-legend" aria-label="Circuit sectors">${colors.map((color, i) => `<span><i style="background:${color}"></i>S${i + 1}</span>`).join("")}</div><span>${esc(circuit.name)} · ${esc(circuit.location)}</span></div>`;
  }
  const coords = circuit.coordinates,
    lat = coords.reduce((sum, p) => sum + p[1], 0) / coords.length;
  const xy = coords.map((p) => [p[0] * Math.cos((lat * Math.PI) / 180), -p[1]]);
  const xs = xy.map((p) => p[0]),
    ys = xy.map((p) => p[1]);
  const minX = Math.min(...xs),
    minY = Math.min(...ys),
    width = Math.max(...xs) - minX,
    height = Math.max(...ys) - minY;
  const scale = Math.min(590 / width, 240 / height);
  const path = xy
    .map(
      (p, i) =>
        `${i ? "L" : "M"}${(45 + (590 - width * scale) / 2 + (p[0] - minX) * scale).toFixed(2)},${(30 + (240 - height * scale) / 2 + (p[1] - minY) * scale).toFixed(2)}`,
    )
    .join(" ");
  return `<div class="circuit-art" data-circuit="${circuit.id}"><svg viewBox="0 0 680 300" role="img" aria-label="${esc(circuit.name)} circuit outline"><path d="${path}" class="circuit-edge"/><path d="${path}" class="circuit-line"/></svg><span>${esc(circuit.name)} · ${esc(circuit.location)}</span></div>`;
}
export function chipIcon(name) {
  const paths = {
    autopilot: '<circle cx="12" cy="12" r="8"/><path d="m8 14 4-7 4 7-4-2Z"/>',
    x3: '<path d="m13 2-8 12h6l-1 8 9-12h-6Z"/>',
    no_negative:
      '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
    wildcard:
      '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2-5.5-3-5.5 3 1-6.2L3 9.6l6.2-.9Z"/>',
    limitless: '<path d="M12 12c-7-13-17 8-5 4l10-8c12-4 2 17-5 4Z"/>',
    final_fix:
      '<path d="m4 20 11-11m-3-5a6 6 0 0 0 8 8l-4-4 1-3 3-1a6 6 0 0 0-8 0ZM3 17l4 4"/>',
  };
  return `<svg class="chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
}
export function racePhotoMarkup(name) {
  const photo = racePhotos[circuitForRace(name)?.id];
  return photo
    ? `<img class="race-photo" src="${esc(photo.path)}" alt="${esc(photo.subject)} (archive venue photograph)" title="${esc(photo.author)} · ${esc(photo.license)} · attribution in footer" width="1100" height="600"/>`
    : "";
}
export function priceTrend(dataset, asset) {
  const rows = dataset.price_history?.[asset.id]?.slice(-4) || [];
  if (rows.length < 2)
    return '<div class="price-trend muted"><span>Price history unavailable</span></div>';
  const values = rows.map((r) => r.price_tenths_m),
    change = values.at(-1) - values[0];
  const low = Math.min(...values),
    high = Math.max(...values),
    range = Math.max(1, high - low);
  const path = values
    .map(
      (v, i) =>
        `${5 + (70 * i) / (values.length - 1)},${25 - (20 * (v - low)) / range}`,
    )
    .join(" ");
  return `<div class="price-trend ${change >= 0 ? "rising" : "falling"}" title="Official round price snapshots, G${rows[0].gameday_id}–G${rows.at(-1).gameday_id}; not intraday prices"><span><small>${rows.length - 1}-round change</small><strong>${change >= 0 ? "+" : "−"}$${(Math.abs(change) / 10).toFixed(1)}m</strong></span><svg viewBox="0 0 80 30" role="img" aria-label="Round prices: ${values.map((v) => "$" + (v / 10).toFixed(1) + "m").join(", ")}"><polyline points="${path}" fill="none" stroke="currentColor" stroke-width="1.6"/></svg></div>`;
}
