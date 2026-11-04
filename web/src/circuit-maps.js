import { esc } from "./text.js";

const colors = ["#e7527d", "#e5bd43", "#55b9cc"];
const palettes = [
  ["#e6007e", "#f5d526", "#4a9ed8"],
  ["#ed1c24", "#00a6d0", "#f5d526"],
];
const geometry = new Map();

export function sectorMarkup(sectors, name, location = "", id = "") {
  return `<div class="circuit-art sector-map" data-circuit="${esc(id)}"><svg viewBox="0 0 680 300" role="img" aria-label="${esc(name)} circuit sector map"><title>${esc(name)} · official sectors 1, 2 and 3</title>${sectors.map((paths, i) => `<path class="sector-surface" fill="${colors[i]}" stroke="${colors[i]}" fill-rule="evenodd" d="${paths.map((p) => p.map((v, j) => `${j ? "L" : "M"}${v.join(",")}`).join(" ") + " Z").join(" ")}"/>`).join("")}</svg><div class="sector-legend" aria-label="Circuit sectors">${colors.map((color, i) => `<span><i style="background:${color}"></i>S${i + 1}</span>`).join("")}</div><span>${esc(name)}${location ? ` · ${esc(location)}` : ""}</span></div>`;
}

export function liveCircuitMarkup(guide, name) {
  return `<div class="circuit-art live-circuit" data-map-name="${esc(name)}" data-map-location="${esc(guide.location)}" data-map-key="${esc(guide.map_asset)}"><div class="circuit-map-status" role="status">Loading circuit sectors…</div><img hidden class="circuit-map-source" crossorigin="anonymous" src="${esc(guide.map_asset)}" alt=""/></div>`;
}

function hue(r, g, b) {
  const high = Math.max(r, g, b),
    low = Math.min(r, g, b),
    range = high - low;
  if (!range) return 0;
  return (
    ((high === r
      ? (g - b) / range
      : high === g
        ? 2 + (b - r) / range
        : 4 + (r - g) / range) /
      6 +
      1) %
    1
  );
}

function roadsFor(data, width, height, color) {
  const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  const target = hue(...rgb),
    mask = new Uint8Array(width * height);
  const black = (x, y) => {
    if (x < 0 || x >= width || y < 0 || y >= height) return false;
    const i = (y * width + x) * 4;
    return data[i + 3] && Math.max(data[i], data[i + 1], data[i + 2]) < 80;
  };
  for (let i = 0; i < mask.length; i++) {
    const j = i * 4,
      r = data[j],
      g = data[j + 1],
      b = data[j + 2];
    if (
      !data[j + 3] ||
      (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2 >= 85 ** 2
    )
      continue;
    const difference = Math.abs(hue(r, g, b) - target);
    if (Math.min(difference, 1 - difference) >= 0.035) continue;
    mask[i] = 1;
  }
  const visited = new Uint8Array(mask.length),
    stack = new Int32Array(mask.length),
    roads = [];
  for (let start = 0; start < mask.length; start++) {
    if (!mask[start] || visited[start]) continue;
    const points = [];
    let size = 1;
    stack[0] = start;
    visited[start] = 1;
    while (size) {
      const i = stack[--size],
        x = i % width,
        y = Math.floor(i / width);
      points.push([x, y]);
      for (const [dx, dy] of [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
        [1, 1],
        [1, -1],
        [-1, 1],
        [-1, -1],
      ]) {
        const nx = x + dx,
          ny = y + dy,
          next = ny * width + nx;
        if (
          nx >= 0 &&
          nx < width &&
          ny >= 0 &&
          ny < height &&
          mask[next] &&
          !visited[next]
        ) {
          visited[next] = 1;
          stack[size++] = next;
        }
      }
    }
    // Detection markers and sector labels can leave short, genuine road islands.
    if (points.length < 30) continue;
    // Classify whole fragments: individual anti-aliased road pixels can lack a
    // dark neighbour, but a genuine stripe has dark road on both sides overall.
    const inside = points.filter(([x, y]) =>
      [
        [4, 0],
        [0, 4],
        [3, 3],
        [3, -3],
      ].some(([dx, dy]) => black(x + dx, y + dy) && black(x - dx, y - dy)),
    ).length;
    if (inside / points.length >= 0.2) roads.push(points);
  }
  if (!roads.length) throw new Error("No verified sector road");
  return roads;
}

function surface(roads, width, height) {
  const mask = new Uint8Array(width * height);
  for (const points of roads)
    for (const [x, y] of points) mask[y * width + x] = 1;
  let connected = roads[0];
  const pending = roads.slice(1);
  while (pending.length) {
    let best = { distance: Infinity };
    for (let index = 0; index < pending.length; index++) {
      const points = pending[index];
      for (const a of connected)
        for (const b of points) {
          const distance = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
          if (distance < best.distance) best = { distance, index, a, b };
        }
    }
    if (best.distance > 120 ** 2) throw new Error("Unresolved sector gap");
    const steps = Math.ceil(Math.sqrt(best.distance));
    for (let t = 0; t <= steps; t++) {
      const x = Math.round(
        best.a[0] + ((best.b[0] - best.a[0]) * t) / Math.max(1, steps),
      );
      const y = Math.round(
        best.a[1] + ((best.b[1] - best.a[1]) * t) / Math.max(1, steps),
      );
      for (let dy = -2; dy <= 2; dy++)
        for (let dx = -2; dx <= 2; dx++) {
          if (x + dx >= 0 && x + dx < width && y + dy >= 0 && y + dy < height)
            mask[(y + dy) * width + x + dx] = 1;
        }
    }
    connected = connected.concat(pending.splice(best.index, 1)[0]);
  }
  return mask;
}

function simplify(points, tolerance = 0.7) {
  if (points.length < 3) return points;
  const a = points[0],
    b = points.at(-1),
    dx = b[0] - a[0],
    dy = b[1] - a[1],
    length = Math.hypot(dx, dy);
  let maximum = 0,
    index = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const x = points[i][0] - a[0],
      y = points[i][1] - a[1];
    const distance = length
      ? Math.abs(x * dy - y * dx) / length
      : Math.hypot(x, y);
    if (distance > maximum) {
      maximum = distance;
      index = i;
    }
  }
  return maximum <= tolerance
    ? [a, b]
    : simplify(points.slice(0, index + 1))
        .slice(0, -1)
        .concat(simplify(points.slice(index)));
}

function contours(mask, width, height) {
  const edges = new Map(),
    stride = width + 1;
  const add = (a, b) => {
    if (!edges.has(a)) edges.set(a, []);
    edges.get(a).push(b);
  };
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const i = y * width + x,
        a = y * stride + x;
      if (!mask[i]) continue;
      if (!y || !mask[i - width]) add(a, a + 1);
      if (x === width - 1 || !mask[i + 1]) add(a + 1, a + stride + 1);
      if (y === height - 1 || !mask[i + width]) add(a + stride + 1, a + stride);
      if (!x || !mask[i - 1]) add(a + stride, a);
    }
  const result = [];
  while (edges.size) {
    const start = edges.keys().next().value,
      path = [];
    let current = start;
    do {
      path.push([current % stride, Math.floor(current / stride)]);
      const next = edges.get(current);
      if (!next) throw new Error("Open sector contour");
      const vertex = next.pop();
      if (!next.length) edges.delete(current);
      current = vertex;
    } while (current !== start);
    if (path.length > 8) result.push(simplify([...path, path[0]]));
  }
  return result;
}

export function extractSectors({ data, width, height }) {
  for (const palette of palettes) {
    try {
      const sectors = palette.map((color) =>
        contours(
          surface(roadsFor(data, width, height, color), width, height),
          width,
          height,
        ),
      );
      const points = sectors.flat(2);
      if (!points.length || sectors.some((s) => !s.length)) continue;
      let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity;
      for (const [x, y] of points) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
      const scale = Math.min(590 / (maxX - minX), 240 / (maxY - minY));
      const offsetX = 45 + (590 - (maxX - minX) * scale) / 2,
        offsetY = 30 + (240 - (maxY - minY) * scale) / 2;
      return sectors.map((paths) =>
        paths.map((p) =>
          p.map(([x, y]) => [
            +(offsetX + (x - minX) * scale).toFixed(2),
            +(offsetY + (y - minY) * scale).toFixed(2),
          ]),
        ),
      );
    } catch {
      /* A different official palette may apply. Never invent missing sectors. */
    }
  }
  throw new Error("Verified sector geometry unavailable");
}

export async function circuitMapEvent(event) {
  const image = event.target;
  if (!image.matches?.("img.circuit-map-source")) return;
  const host = image.parentElement,
    { mapKey, mapName, mapLocation } = host.dataset;
  try {
    if (event.type === "error") throw new Error("Map unavailable");
    if (!geometry.has(mapKey)) {
      geometry.set(
        mapKey,
        new Promise((resolve, reject) =>
          setTimeout(() => {
            try {
              const canvas = document.createElement("canvas");
              canvas.width = image.naturalWidth;
              canvas.height = image.naturalHeight;
              const ctx = canvas.getContext("2d", { willReadFrequently: true });
              ctx.drawImage(image, 0, 0);
              resolve(
                extractSectors(
                  ctx.getImageData(0, 0, canvas.width, canvas.height),
                ),
              );
            } catch (error) {
              reject(error);
            }
          }, 0),
        ),
      );
    }
    const sectors = await geometry.get(mapKey);
    host.outerHTML = sectorMarkup(sectors, mapName, mapLocation);
  } catch {
    geometry.delete(mapKey);
    host.innerHTML = `<div class="circuit-map-status">Circuit sectors unavailable.</div><a class="circuit-source" href="${esc(mapKey)}" target="_blank" rel="noopener noreferrer">Open the detailed official map</a>`;
  }
}
