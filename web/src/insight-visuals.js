import guides from "./track-guides.json" with { type: "json" };
import {
  esc,
  points,
  teamColor,
  helmet,
  car,
  constructorName,
} from "./views.js";
import {
  portrait,
  circuitForRace,
  circuitMarkup,
  racePhotoMarkup,
} from "./visuals.js";

const pct = (n) =>
  Number.isFinite(n) ? `${(100 * n).toFixed(1)}%` : "Unavailable";
const total = (scores) => scores.reduce((a, b) => a + b, 0);
const num = (n, digits = 0) =>
  Number.isFinite(n) ? n.toFixed(digits) : "Unavailable";
const stat = (label, value, note = "") =>
  `<div><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
const symbol = (path) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
const cloud = symbol(
  '<path d="M6 16a4 4 0 1 1 1-7 5 5 0 0 1 9-1 4 4 0 1 1 2 8"/><path d="m8 18-1 3m6-3-1 3m6-3-1 3"/>',
);
const thermometer = symbol(
  '<path d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0Z"/><path d="M12 9v9"/>',
);
const windIcon = symbol(
  '<path d="M3 8h12a3 3 0 1 0-3-3M3 12h16a2 2 0 1 1-2 2M3 16h7a3 3 0 1 1-3 3"/>',
);

export function insightHero(dataset, round, insight) {
  const circuit = circuitForRace(round.name);
  const candidate = guides[circuit?.id];
  const guide = candidate?.season === dataset.season ? candidate : null;
  const spec = round.track_spec;
  return `<div class="insight-ticker"><span><i></i> Round ${round.round} · ${esc(circuit?.name || round.name)}</span><span>${round.sprint ? "Sprint format" : "Grand Prix weekend"}</span><span>${insight.simulations.toLocaleString()} joint simulations</span><span>Uncalibrated model</span></div>
    <section class="insight-hero" aria-label="Race Insights circuit briefing">
      ${guide ? `<img class="insight-hero-photo" src="${guide.photo}" alt="${esc(circuit.name)} — official F1 venue photograph" width="1600" height="900" fetchpriority="high"/>` : racePhotoMarkup(round.name)}
      <div class="insight-hero-content"><div class="insight-hero-copy"><div class="insight-hero-badges"><span>Race Insights</span><span>${dataset.season} circuit briefing</span></div><h1>${esc(round.name)}</h1><p class="insight-hero-location">${esc(circuit?.location || "Circuit details unavailable")}${spec ? ` · ${spec.race_laps} laps · ${num(spec.length_km, 3)} km` : ""}</p><p class="insight-hero-description">${esc(guide?.description || "Explore the published race probabilities, Fantasy forecasts and championship outlook for this weekend.")}</p><div class="insight-hero-stats">${stat("Lap record", guide?.lap_record || "Unavailable", guide?.record_driver || "Official record not verified")}${stat("Race distance", spec ? `${num(spec.race_distance_km, 3)} km` : "Unavailable", spec ? `${spec.race_laps} scheduled laps` : "Track specification unavailable")}${stat("First Grand Prix", guide ? String(guide.first_gp) : "Unavailable", circuit?.name || "")}${stat("Forecast sample", `${insight.form_samples.R} GPs`, `${insight.form_samples.S} Sprints · recent form`)}</div></div>
      <figure class="insight-track-map"><figcaption><strong>Circuit map & ${guide?.zones_published ? "activation zones" : "sector splits"}</strong><span>${dataset.season} layout</span></figcaption>${guide ? `<a class="insight-map-link" href="${guide.map}" target="_blank" rel="noopener noreferrer" aria-label="Open full-size ${esc(circuit.name)} official circuit map"><img src="${guide.map}" alt="Official ${dataset.season} ${esc(circuit.name)} map: numbered turns and sector splits${guide.zones_published ? ", straight-mode zones, overtake detection and activation points" : ""}" width="1280" height="704"/></a><div class="insight-map-key">${guide.sector_colors.map((color, i) => `<span><i style="background:${color}"></i>Sector ${i + 1}</span>`).join("")}</div><p>2026 replaces DRS with straight mode and overtake mode. ${guide.zones_published ? "Zones are marked on the official map; open it for detail." : "Activation zones are not annotated in this published guide; no positions are inferred."}</p><a class="insight-source" href="${guide.source}" target="_blank" rel="noopener noreferrer">Formula 1 circuit guide · map & track records ↗</a>` : `${circuitMarkup(round.name)}<p>Activation-zone positions are not verified for this round. Outline only.</p>`}</figure></div>
    </section>`;
}

export function weatherBriefing(round) {
  const w = round.weather;
  const ready = w?.status === "available";
  const note =
    w?.status === "outside_horizon"
      ? "Outside the 16-day forecast window"
      : "Forecast unavailable";
  const cards = [
    [
      cloud,
      "Rain outlook",
      ready ? `${num(w.daily_rain_probability_max)}%` : "Unavailable",
      ready ? "Highest daily precipitation chance" : note,
      "blue",
    ],
    [
      thermometer,
      "Air temperature",
      ready ? `${num(w.air_min_c)}–${num(w.air_max_c)}°C` : "Unavailable",
      "Weekend air range · not track temperature",
      "orange",
    ],
    [
      windIcon,
      "Maximum wind",
      ready ? `${num(w.wind_max_kmh)} km/h` : "Unavailable",
      ready ? "Highest daily 10 m wind forecast" : note,
      "teal",
    ],
    [
      symbol('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
      "Weekend format",
      round.sprint ? "Sprint" : "Grand Prix",
      round.sprint ? "Qualifying + Sprint + Race" : "Qualifying + Race",
      "red",
    ],
  ];
  return `<section class="insight-weather" aria-label="Selected weekend weather and format"><div class="insight-weather-cards">${cards.map(([icon, label, value, detail, color]) => `<article class="weather-tile ${color}"><span class="weather-icon">${icon}</span><div><h2>${label}</h2><strong>${value}</strong><p>${esc(detail)}</p></div></article>`).join("")}</div>${ready ? `<div class="weather-day-grid">${(w.daily || []).map((d) => `<article><span>${esc(new Date(d.date + "T12:00:00Z").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }))}</span><strong>${num(d.air_min_c)}–${num(d.air_max_c)}°C</strong><span class="weather-rain-bar" aria-hidden="true"><i style="width:${d.rain_probability}%"></i></span><small>${num(d.rain_probability)}% rain · ${num(d.wind_max_kmh)} km/h wind</small></article>`).join("")}</div><p class="insight-weather-source"><a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo · CC BY 4.0</a> · daily forecasts, ${esc(w.start_date)}–${esc(w.end_date)} UTC · fetched ${esc(w.fetched_at)} · display-only, not a model input</p>` : `<p class="insight-weather-source">${esc(note)}. Weather is display-only; no climatology or zero-rain estimate is substituted.</p>`}</section>`;
}

function rankedAssets(dataset, round, population) {
  return dataset.assets
    .filter(
      (a) => a.kind === (population === "drivers" ? "DRIVER" : "CONSTRUCTOR"),
    )
    .map((a) => ({ a, scores: round.forecasts[a.id] }))
    .sort(
      (a, b) =>
        total(b.scores) - total(a.scores) || a.a.name.localeCompare(b.a.name),
    );
}

export function fantasyChart(dataset, round, population) {
  const rows = rankedAssets(dataset, round, population).slice(0, 8);
  const max = Math.max(
    1,
    ...rows.map(({ scores }) => scores.reduce((s, v) => s + Math.abs(v), 0)),
  );
  return `<section class="panel insight-output"><div class="section-heading"><div><span class="insight-kicker">Weekend forecast</span><h2>${population === "drivers" ? "Driver" : "Constructor"} Fantasy output</h2><p>Top ${rows.length} by unboosted expected points · R${round.round}</p></div></div><div class="session-chart-key"><span><i class="session-q"></i>Qualifying</span>${round.sprint ? '<span><i class="session-s"></i>Sprint</span>' : ""}<span><i class="session-r"></i>Race</span></div><ol class="fantasy-chart">${rows.map(({ a, scores }) => `<li style="--team-color:${teamColor(dataset, a)}"><div class="fantasy-chart-label"><span><i></i>${esc(a.name)}</span><strong>${points(total(scores))} <small>pts</small></strong></div><div class="fantasy-session-values"><span>Q ${points(scores[0])}</span>${round.sprint ? `<span>S ${points(scores[1])}</span>` : ""}<span>R ${points(scores[2])}</span></div><div class="signed-chart" aria-hidden="true"><span class="signed-negative">${scores.map((v, i) => `<i class="session-${["q", "s", "r"][i]}" style="width:${(100 * Math.max(0, -v)) / max}%"></i>`).join("")}</span><span class="signed-positive">${scores.map((v, i) => `<i class="session-${["q", "s", "r"][i]}" style="width:${(100 * Math.max(0, v)) / max}%"></i>`).join("")}</span></div></li>`).join("")}</ol><p class="insight-note">Negative components extend left of zero. Q / S / R values are the accessible chart data. Excludes Boost, chips and transfers.</p></section>`;
}

export function championshipChart(dataset, insight, population) {
  if (insight.championship.status !== "ready")
    return `<section class="panel insight-champ-chart"><span class="insight-kicker">Season outlook</span><h2>Championship horizon</h2><p>${esc(insight.championship.message)}</p></section>`;
  const eligible = insight.championship[population].filter(
    (r) => r.title_eligible === true,
  );
  const eliminated = insight.championship[population].filter(
    (r) => r.title_eligible === false,
  ).length;
  const rows = eligible.slice(0, 5);
  const max = Math.max(1, ...rows.map((r) => r.interval80[1]));
  return `<section class="panel insight-champ-chart"><div class="section-heading"><div><span class="insight-kicker">Title contention · end-of-season projection</span><h2>Championship horizon</h2><p>Real F1 points · leading ${rows.length} of ${eligible.length} mathematically eligible contenders</p></div></div><div class="champ-chart-key"><span><i></i>Observed</span><span><i></i>Expected remaining</span></div><ol>${rows
    .map((r) => {
      const a = dataset.assets.find((a) => a.id === r.asset_id);
      return `<li style="--team-color:${a ? teamColor(dataset, a) : "#68635f"}"><div><span>${esc(r.name)}</span><strong>${points(r.projected)} <small>pts</small></strong></div><div class="champ-stacked-bar" aria-hidden="true"><i style="width:${(100 * r.observed) / max}%"></i><b style="width:${(100 * r.remaining) / max}%"></b></div><p>${points(r.observed)} observed + ${points(r.remaining)} expected · 80% range ${points(r.interval80[0])}–${points(r.interval80[1])} · maximum possible ${points(r.max_final)}</p></li>`;
    })
    .join(
      "",
    )}</ol><p class="insight-note">${eliminated} mathematically eliminated entrants hidden. Eligibility assumes maximum GP and Sprint points with rivals scoring zero; equal-point ceilings use GP finish countback, retaining unresolved ties. Historical records retain everyone. ${dataset.rounds.length} remaining rounds; uncalibrated simulation ranges.</p></section>`;
}

export function contenderCards(dataset, round, probabilities, population) {
  const rows = rankedAssets(dataset, round, population).slice(0, 2);
  return `<div class="insight-contenders">${rows
    .map(({ a, scores }, i) => {
      const p = probabilities?.[population]?.[a.id] || {};
      return `<article class="panel contender-card" style="--team-color:${teamColor(dataset, a)}"><div class="contender-rank"><span>${i === 0 ? "Highest Fantasy forecast" : "Next Fantasy forecast"}</span><strong>${points(total(scores))} pts</strong></div><div class="contender-body"><div class="contender-photo">${portrait(a, a.kind === "DRIVER" ? helmet() : car())}</div><div><h2>${esc(a.name)}</h2><p>${esc(constructorName(dataset, a))}</p><span class="tag">Unboosted Fantasy points</span></div></div><div class="contender-metrics"><div><span>Race win</span><strong>${pct(p.win)}</strong></div><div><span>Podium</span><strong>${pct(p.podium)}</strong></div><div><span>Top 10</span><strong>${pct(p.top10)}</strong></div></div><p class="insight-note">${population === "constructors" ? "Outcome probabilities refer to at least one car." : "Race probabilities are separate from Fantasy scoring."}</p></article>`;
    })
    .join("")}</div>`;
}

export function podiumCards(dataset, probabilities, population) {
  const rows = dataset.assets
    .filter(
      (a) => a.kind === (population === "drivers" ? "DRIVER" : "CONSTRUCTOR"),
    )
    .map((a) => ({ a, p: probabilities?.[population]?.[a.id] }))
    .filter((r) => Number.isFinite(r.p?.podium))
    .sort((a, b) => b.p.podium - a.p.podium)
    .slice(0, 5);
  if (!rows.length) return "";
  return `<section class="panel insight-podiums"><div class="section-heading"><div><span class="insight-kicker">Simulated race outcomes</span><h2>${population === "drivers" ? "Driver" : "Constructor"} podium probabilities</h2><p>Leading ${rows.length} · ${population === "constructors" ? "at least one car on the podium" : "probabilities overlap across drivers"}</p></div></div><div class="podium-card-grid">${rows.map(({ a, p }) => `<article style="--team-color:${teamColor(dataset, a)}"><div class="podium-portrait">${portrait(a, a.kind === "DRIVER" ? helmet() : car())}</div><h3>${esc(a.name)}</h3><div class="podium-ring"><svg viewBox="0 0 42 42" aria-hidden="true"><circle cx="21" cy="21" r="17"/><circle cx="21" cy="21" r="17" pathLength="100" stroke-dasharray="${100 * p.podium} 100"/></svg><strong>${pct(p.podium)}</strong></div><span>Podium chance</span><small>Race win ${pct(p.win)}</small></article>`).join("")}</div></section>`;
}
