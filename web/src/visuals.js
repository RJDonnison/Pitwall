import photos from "./media.json" with { type: "json" };
import circuits from "./circuits.json" with { type: "json" };
import racePhotos from "./race-media.json" with { type: "json" };
import { esc } from "./text.js";

export const logo = () =>
  '<svg class="pitwall-logo" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="6" fill="#1c1917"/><path d="m8 30 7-20h17l-3 8H18l-4 12Z" fill="#fbfbfa"/><path d="M20 22h10l-2 6H18Z" fill="#d94636"/></svg>';

export function footerMarkup() {
  return `<footer class="site-footer"><div class="footer-principle"><span>Strategic principle</span><h2>Think in seasons. Check before you change.</h2></div><div class="footer-columns"><section><div class="footer-column-heading"><h3>One joint plan</h3><span>Optimizer</span></div><p>Five drivers, two constructors, Boost, chips and transfer penalties. One exact season plan, calculated on your device.</p><a href="https://fantasy.formula1.com/en/game-rules" target="_blank" rel="noopener noreferrer">Official Fantasy rules ↗</a></section><section><div class="footer-column-heading"><h3>Forecasts, not promises</h3><span>Forecasts</span></div><p>Historical inputs precede the weekend. Future prices stay at today's values. Final Fix is a separate post-qualifying decision.</p><a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Weather by Open-Meteo · CC BY 4.0 ↗</a></section><section><div class="footer-column-heading"><h3>Your teams stay here</h3><span>Privacy</span></div><p>Three profiles, stored in this browser. No account sign-in, server-side team storage or automatic submission.</p><p>Check the official game's prices, eligibility and lock before making changes.</p></section></div><div class="footer-status"><span class="footer-brand">${logo()}<b>Pitwall</b> · Independent Fantasy planning</span><details class="data-status-details"><summary><span id="publication-status" role="status">Loading public data…</span></summary><p>The site publishes official prices periodically. When the official Fantasy feeds block browser access, planning uses this published snapshot rather than a live account check. New plans are blocked once the publication is six hours old.</p><p id="publication-window"></p></details></div><p class="footer-disclaimer">Not affiliated with Formula 1. No account submission.</p>${creditsMarkup()}</footer>`;
}
export function portrait(asset, fallback = "") {
  const photo = photos[asset.id];
  return photo
    ? `<img class="asset-photo ${asset.kind === "CONSTRUCTOR" ? "car-photo" : ""} ${photo.repository ? "official-photo" : ""}" src="${esc(photo.path)}${photo.revision ? `?v=${esc(photo.revision.slice(0, 12))}` : ""}" alt="${esc(photo.subject)}${photo.repository ? "" : " (archive photograph)"}" title="${esc(photo.author)} · ${esc(photo.license)} · full attribution in footer" loading="lazy" width="480" height="480"/>`
    : fallback;
}
export function creditsMarkup() {
  return `<details id="image-credits"><summary>Image & circuit credits</summary><p>Driver and car images: Formula 1, via the requested TracingInsights 2026 repository (Apache-2.0 repository licence). Source imagery is not labelled Creative Commons. Venue photographs retain their individual Commons licences. No endorsement is implied.</p><ul>${Object.values(
    { ...photos, ...racePhotos },
  )
    .map(
      (p) =>
        `<li><a href="${esc(p.source)}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · ${esc(p.subject)}</a> — ${esc(p.author)} · <a href="${esc(p.license_url)}" target="_blank" rel="noopener noreferrer">${esc(p.license)}</a>${p.repository ? ` · <a href="${esc(p.repository)}" target="_blank" rel="noopener noreferrer">Pinned source</a>` : ""}. ${esc(p.changes)}</li>`,
    )
    .join(
      "",
    )}</ul><p>Circuit coordinates © 2019–2025 Tomislav Bacinger, <a href="https://github.com/bacinger/f1-circuits" target="_blank" rel="noopener noreferrer">f1-circuits</a> · <a href="./media/CIRCUITS-LICENSE.txt">MIT licence</a>. Projected into illustrative SVG outlines; not live track maps.</p></details>`;
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
