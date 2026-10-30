import { total } from "./optimizer.js";
import { esc } from "./text.js";
import {
  portrait,
  priceTrend,
  circuitMarkup,
  racePhotoMarkup,
  chipIcon,
} from "./visuals.js";
export { esc } from "./text.js";
export const points = (value) =>
  Number(value).toLocaleString(undefined, {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
export const money = (value) => `$${(value / 10).toFixed(1)}m`;
export const date = (value) =>
  new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
export const shortRace = (name) => name.replace(" Grand Prix", "");
export const chipNames = {
  autopilot: "Autopilot",
  x3: "3× Boost",
  no_negative: "No Negative",
  wildcard: "Wildcard",
  limitless: "Limitless",
  final_fix: "Final Fix",
};
export const chipDescriptions = {
  autopilot: "2× goes to the best selected driver across the whole weekend.",
  x3: "Triple one driver, with a different driver on regular 2×.",
  no_negative:
    "Removes negative scoring categories; transfer penalties still apply.",
  wildcard: "Unlimited transfers within your budget.",
  limitless: "Unlimited budget and transfers, then your original team returns.",
  final_fix:
    "One future-only swap after qualifying. Reassess in the official window; not spent by this pre-weekend plan.",
};
export const delta = (value) =>
  `${value < 0 ? "−" : "+"}${points(Math.abs(value))}`;
export function constructorName(dataset, a) {
  return a.kind === "CONSTRUCTOR"
    ? a.name
    : dataset.assets.find(
        (c) => c.kind === "CONSTRUCTOR" && c.team_id === a.team_id,
      )?.name || "Driver";
}
export function teamColor(dataset, a) {
  const name = constructorName(dataset, a).toLowerCase();
  return (
    Object.entries({
      mclaren: "#dc670f",
      ferrari: "#b81b25",
      mercedes: "#007b72",
      williams: "#1b64a6",
      aston: "#006557",
      alpine: "#2085a8",
      "red bull": "#283d8e",
      "racing bulls": "#475fd2",
      audi: "#bd3035",
      haas: "#8b3438",
      cadillac: "#525456",
    }).find(([key]) => name.includes(key))?.[1] || "#555853"
  );
}
export function icon(name, cls = "") {
  const paths = {
    transfer: '<path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4 4-4-4 4-4"/>',
    bolt: '<path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z"/>',
    shield:
      '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    flag: '<path d="M5 22V3m0 1c5-5 9 5 15 0v11c-6 5-10-5-15 0"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
  };
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.grid}</svg>`;
}
export function helmet() {
  return '<svg class="helmet" viewBox="0 0 80 64" aria-hidden="true"><path d="M12 47C6 27 19 9 40 9s33 18 29 36l-6 10H20Z" fill="currentColor" opacity=".13"/><path d="M12 47C6 27 19 9 40 9s33 18 29 36l-6 10H20Zm1-14h52M31 55l-2-14h37M20 24c5-6 11-9 18-9" fill="none" stroke="currentColor" stroke-width="3"/><path d="M31 34h36l1 8H30Z" fill="currentColor" opacity=".65"/></svg>';
}
export function car() {
  return '<svg class="car-art" viewBox="0 0 300 82" aria-hidden="true"><path d="m17 59 34-3 23-12 27-1 26-15h35l10 17 36 3 32 10h39v9H17Z" fill="currentColor" opacity=".8"/><path d="m27 48 7-16h13v22m210-1 2-23h16v28M119 27h38m-50 25h81" fill="none" stroke="currentColor" stroke-width="3"/><circle cx="70" cy="63" r="14" fill="var(--paper)" stroke="currentColor" stroke-width="5"/><circle cx="230" cy="63" r="14" fill="var(--paper)" stroke="currentColor" stroke-width="5"/></svg>';
}
function ring(percent) {
  return `<svg class="ring" viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="17" fill="none" stroke="var(--rule)" stroke-width="5"/><circle cx="22" cy="22" r="17" fill="none" stroke="var(--red)" stroke-width="5" stroke-dasharray="${Math.max(0, Math.min(100, percent)) * 1.068} 106.8" transform="rotate(-90 22 22)"/></svg>`;
}
export function profilesMarkup(dataset, profiles, active) {
  return profiles
    .map((t, i) => {
      const chosen = dataset.assets.filter((a) => t.selected.includes(a.id));
      const cost = total(chosen.map((a) => a.price_tenths_m));
      return `<button class="profile-card ${i === active ? "is-active" : ""}" data-team="${i}" aria-pressed="${i === active}"><div><h3>${esc(t.name)}</h3><span class="tag ${i === active ? "red" : ""}">${i === active ? "Active" : "Switch team"}</span></div><p>${chosen.filter((a) => a.kind === "DRIVER").length}/5 drivers · ${chosen.filter((a) => a.kind === "CONSTRUCTOR").length}/2 constructors · local profile</p><div class="profile-metrics">${ring((cost / t.budget) * 100)}<span><small>Lineup valuation</small><strong>${money(cost)}</strong></span><span><small>Budget cap</small><strong>${money(t.budget)}</strong></span></div></button>`;
    })
    .join("");
}
export function rosterMarkup(dataset, team, round) {
  return ["DRIVER", "CONSTRUCTOR"]
    .map(
      (kind) =>
        `<h2 class="roster-section-heading">${kind === "DRIVER" ? "Active drivers" : "Constructors"}<span>${team.selected.filter((id) => dataset.assets.find((a) => a.id === id)?.kind === kind).length}/${kind === "DRIVER" ? 5 : 2}</span></h2><div class="roster-cards ${kind === "CONSTRUCTOR" ? "constructor-cards" : ""}">${Array.from(
          { length: kind === "DRIVER" ? 5 : 2 },
          (_, i) => {
            const a = dataset.assets.filter(
              (a) => a.kind === kind && team.selected.includes(a.id),
            )[i];
            if (!a)
              return `<a href="#asset-registry" class="roster-empty"><span>+</span><strong>Choose ${kind === "DRIVER" ? "driver" : "constructor"} ${i + 1}</strong></a>`;
            if (kind === "CONSTRUCTOR")
              return `<article class="roster-card constructor-roster" style="--team-color:${teamColor(dataset, a)}"><div class="constructor-heading"><div><small>Constructor ${i + 1}</small><h3>${esc(a.name)}</h3></div><strong>${money(a.price_tenths_m)}</strong></div><div class="constructor-visual"><div class="roster-photo">${portrait(a, car())}</div>${priceTrend(dataset, a)}</div><button class="card-action" data-remove="${esc(a.id)}" aria-label="Remove ${esc(a.name)}">Replace ${icon("transfer")}</button></article>`;
            return `<article class="roster-card" style="--team-color:${teamColor(dataset, a)}"><div class="driver-card-top"><div class="roster-photo">${portrait(a, helmet())}</div><div><strong class="driver-tla">${esc(a.tla || "F1")}</strong><small>${esc(constructorName(dataset, a))}</small></div></div><h3>${esc(a.name)}</h3><strong class="roster-price">${money(a.price_tenths_m)}</strong>${priceTrend(dataset, a)}<button class="card-action" data-remove="${esc(a.id)}" aria-label="Remove ${esc(a.name)}">Replace ${icon("transfer")}</button></article>`;
          },
        ).join("")}</div>`,
    )
    .join("");
}
export function registryCardMarkup(dataset, team, a) {
  const selected = team.selected.includes(a.id);
  const count = dataset.assets.filter(
    (row) => row.kind === a.kind && team.selected.includes(row.id),
  ).length;
  const forecast = total(dataset.rounds[0].forecasts[a.id]);
  return `<article class="market-card ${selected ? "selected" : ""}" style="--team-color:${teamColor(dataset, a)}"><div class="market-card-title"><div class="registry-photo">${portrait(a, a.kind === "DRIVER" ? helmet() : car())}</div><div><h3>${esc(a.name)}</h3>${a.kind === "DRIVER" ? `<small>${esc(constructorName(dataset, a))}</small>` : ""}</div><strong>${money(a.price_tenths_m)}</strong></div>${priceTrend(dataset, a)}<div class="market-card-bottom"><span class="registry-estimate" title="Unboosted Fantasy forecast for ${esc(dataset.rounds[0].name)}"><strong>${points(forecast)}</strong> est. pts</span><button class="registry-add" data-select="${esc(a.id)}" aria-label="${selected ? "Remove" : "Add"} ${esc(a.name)}" aria-pressed="${selected}" ${!selected && count >= (a.kind === "DRIVER" ? 5 : 2) ? "disabled" : ""}>${icon(selected ? "minus" : "plus")}<span>${selected ? "Remove" : "Add"}</span></button></div></article>`;
}
export function allocationMarkup(dataset, team) {
  const chosen = dataset.assets.filter((a) => team.selected.includes(a.id));
  const drivers = total(
    chosen.filter((a) => a.kind === "DRIVER").map((a) => a.price_tenths_m),
  );
  const constructors = total(
    chosen.filter((a) => a.kind === "CONSTRUCTOR").map((a) => a.price_tenths_m),
  );
  const cost = drivers + constructors,
    free = team.budget - cost;
  const width = (n) => (100 * n) / Math.max(cost, team.budget);
  return `<section class="panel allocation"><div class="section-heading"><h2>Budget allocation</h2><strong>${money(cost)} / ${money(team.budget)}</strong></div><div class="allocation-bar" role="img" aria-label="Drivers ${money(drivers)}, constructors ${money(constructors)}, ${free >= 0 ? "free" : "over cap"} ${money(Math.abs(free))}"><span style="width:${width(drivers)}%"></span><span style="width:${width(constructors)}%"></span><span style="width:${width(Math.max(0, free))}%"></span></div><div class="allocation-key"><span><i></i>Drivers<strong>${money(drivers)}</strong></span><span><i></i>Constructors<strong>${money(constructors)}</strong></span><span><i></i>Available<strong class="${free < 0 ? "negative" : ""}">${money(free)}</strong></span></div>${free < 0 ? `<p class="negative">Above the entered budget: ${money(-free)} over cap${team.active === "limitless" ? " · Limitless active" : " · adjust the roster or budget"}</p>` : ""}</section>`;
}
function chart(values, labels, cls = "trajectory-chart") {
  const low = Math.min(0, ...values),
    high = Math.max(1, ...values);
  const x = (i) => 40 + (i / Math.max(1, values.length - 1)) * 720;
  const y = (v) => 150 - ((v - low) / (high - low)) * 120;
  return `<svg class="${cls}" viewBox="0 0 800 200" role="img" aria-label="${esc(labels.map((l, i) => `${l}: ${points(values[i])} points`).join(", "))}"><path class="chart-grid" d="M40 30H760M40 90H760M40 150H760"/><polyline class="chart-line" points="${values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>${values.map((v, i) => `<circle class="chart-dot" cx="${x(i)}" cy="${y(v)}" r="4"/><text x="${x(i)}" y="${y(v) - 12}" text-anchor="middle">${points(v)}</text><text class="chart-label" x="${x(i)}" y="184" text-anchor="middle">${esc(labels[i])}</text>`).join("")}</svg>`;
}
export function heroMarkup(dataset) {
  const r = dataset.rounds[0];
  const spec = r.track_spec,
    weather = r.weather;
  const context = `<aside class="race-context" aria-label="Track and weather">${circuitMarkup(r.name)}<div class="race-context-readings"><section><span class="eyebrow">Track spec</span>${spec ? `<strong>${Number(spec.length_km).toFixed(3)} <small>km</small> <i>·</i> ${spec.race_laps} <small>laps</small></strong><p>${Number(spec.race_distance_km).toFixed(3)} km race distance</p>` : "<p>Track details unavailable.</p>"}</section><section class="weather-context"><span class="eyebrow">Weather</span>${weather?.status === "available" ? `<strong>${Math.round(weather.air_min_c)}–${Math.round(weather.air_max_c)}° <small>air</small></strong><div class="weather-metrics"><span>${Math.round(weather.daily_rain_probability_max)}% <small>rain chance</small></span><span>${Math.round(weather.wind_max_kmh)} <small>km/h wind</small></span></div>` : `<p>${weather?.status === "outside_horizon" ? "Outside the 16-day forecast window." : "Unavailable."}</p>`}</section></div></aside>`;
  return `<div class="race-overview"><section class="race-hero circuit-hero">${racePhotoMarkup(r.name)}<div class="race-title"><span class="race-kicker">Round ${r.round} · ${r.sprint ? "Sprint" : "Regular"} weekend</span><h1>${esc(r.name)}</h1><p>${dataset.rounds.length} rounds remaining · ${esc(new Date(r.first_session_utc).toLocaleDateString(undefined, { day: "numeric", month: "long" }))}</p></div></section>${context}</div>`;
}
export function referencePoints(dataset, team) {
  if (team.selected.length !== 7) return null;
  return dataset.rounds.map((r) => {
    const selected = dataset.assets.filter((a) => team.selected.includes(a.id));
    return (
      total(selected.map((a) => total(r.forecasts[a.id]))) +
      Math.max(
        ...selected
          .filter((a) => a.kind === "DRIVER")
          .map((a) => total(r.forecasts[a.id])),
      )
    );
  });
}
function transferNames(dataset, ids) {
  return ids
    .map((id) => dataset.assets.find((a) => a.id === id))
    .map(
      (a) =>
        `<span><strong>${esc(a.name)}</strong><small>${money(a.price_tenths_m)}</small></span>`,
    )
    .join("");
}
export function transfersMarkup(dataset, outgoing, incoming) {
  return `<div class="transfer-lists" tabindex="0" role="region" aria-label="Roster changes; scroll for all selections">${[
    ["out", "Remove", outgoing],
    ["in", "Bring in", incoming],
  ]
    .map(
      ([direction, label, ids]) =>
        `<section class="transfer-column transfer-${direction}" aria-label="${label} selections"><h3>${icon(direction === "out" ? "minus" : "plus")}${label}<span>${ids.length}</span></h3><ul>${
          ids.length
            ? ids
                .map((id) => {
                  const a = dataset.assets.find((row) => row.id === id);
                  const gain =
                    total(dataset.rounds[0].forecasts[a.id]) *
                    (direction === "out" ? -1 : 1);
                  return `<li><span class="transfer-status">${direction === "out" ? "OUT" : "IN"}</span><div><strong>${esc(a.name)}</strong><small>${esc(constructorName(dataset, a))} · ${money(a.price_tenths_m)}</small></div><span class="transfer-estimate ${gain < 0 ? "negative" : "positive"}" title="Unboosted next-race points">${delta(gain)}<small>pts</small></span></li>`;
                })
                .join("")
            : `<li class="transfer-empty">${direction === "out" ? "Keep the current roster" : "No additions"}</li>`
        }</ul></section>`,
    )
    .join("")}</div>`;
}
function transferDirective(dataset, team, round) {
  return `<section class="panel directive roster-directive"><div class="directive-heading"><span>${icon("transfer")}Roster changes</span><span class="tag">${round.transfer_penalty ? `−${round.transfer_penalty} pts` : "No penalty"}</span></div><h2>${round.transfers} ${round.transfers === 1 ? "transfer" : "transfers"}</h2>${transfersMarkup(dataset, round.out, round.in)}<div class="directive-footer">${round.chip === "limitless" ? "Limitless" : `Cash: ${money(team.budget - round.cost)}`}<span>${round.chip === "wildcard" || round.chip === "limitless" || team.initial ? "Unlimited" : `${2 + team.carry} free`}</span></div></section>`;
}
function boostDirective(dataset, round) {
  const automatic = round.chip === "autopilot";
  const driver = dataset.assets.find((a) => a.id === round.boost);
  const entry = round.entries.find((e) => e.id === round.boost);
  const value = automatic
    ? total(round.entries.map((e) => total(e.extra)))
    : entry.total;
  return `<section class="panel directive boost-directive ${automatic ? "boost-automatic" : "boost-driver"}">
    ${!automatic ? `<div class="boost-backdrop" aria-hidden="true">${portrait(driver, helmet())}</div>` : ""}
    <div class="directive-heading"><span>${icon("bolt")}Driver Boost</span><span class="tag">2×</span></div>
    <div class="boost-visual">${
      automatic
        ? `<div class="boost-candidates" aria-label="Autopilot selects among these five drivers">${round.entries
            .filter(
              (e) =>
                dataset.assets.find((a) => a.id === e.id).kind === "DRIVER",
            )
            .map(
              (e) =>
                `<span>${portrait(
                  dataset.assets.find((a) => a.id === e.id),
                  helmet(),
                )}</span>`,
            )
            .join("")}</div>`
        : ""
    }<div><h2>${automatic ? "Best selected driver" : esc(driver.name)}</h2><p>${automatic ? "Autopilot · whole-weekend winner" : esc(constructorName(dataset, driver))}</p></div></div>
    <div class="boost-output"><strong>${points(value)}</strong><span>${automatic ? "expected extra Boost points" : "forecast pts including 2×"}</span></div>
     ${!automatic && round.x3 ? `<p>3×: ${esc(dataset.assets.find((a) => a.id === round.x3).name)}</p>` : ""}
  </section>`;
}
export function strategyMarkup(
  dataset,
  team,
  result,
  busy,
  selectedRound = 0,
  error = "",
) {
  // Presentation summaries distinguish each selection's gross total from the
  // round's net points after transfer penalties.
  if (result)
    result = {
      ...result,
      selectedRound,
      rounds: result.rounds.map((r) => ({
        ...r,
        transfer_penalty: r.penalty,
        entries: r.entries.map((e) => ({ ...e, total: e.points })),
      })),
    };
  if (!result)
    return `${heroMarkup(dataset, team, result)}<section class="panel welcome" role="status"><h2>${busy ? "Updating strategy…" : error ? "Strategy unavailable" : team.selected.length === 7 ? "Preparing strategy…" : "Choose your starting seven"}</h2><p>${error ? esc(error) : busy ? "Optimizing the remaining season." : team.selected.length === 7 ? "Changes are calculated automatically." : "Five drivers and two constructors in the Garage."}</p></section>`;
  const first = result.rounds[0],
    round = result.rounds[selectedRound];
  const reference = referencePoints(dataset, team);
  const nextChip = result.rounds.slice(1).find((r) => r.chip);
  const driverScore = total(
    first.entries
      .filter(
        (e) => dataset.assets.find((a) => a.id === e.id).kind === "DRIVER",
      )
      .map((e) => e.total),
  );
  const constructorScore = total(
    first.entries
      .filter(
        (e) => dataset.assets.find((a) => a.id === e.id).kind === "CONSTRUCTOR",
      )
      .map((e) => e.total),
  );
  const denominator = Math.max(1, first.points, reference[0]);
  let cumulative = 0;
  return `${heroMarkup(dataset, team, result)}<div class="directive-grid">${transferDirective(dataset, team, first)}${boostDirective(dataset, first)}<section class="panel directive chip-directive"><div class="directive-heading"><span>${icon("shield")}Chip plan</span><span class="tag ${first.chip ? "red" : ""}">${first.chip ? "Use" : "Save"}</span></div><div class="chip-callout ${first.chip ? `plan-chip chip-${first.chip}` : ""}">${first.chip ? chipIcon(first.chip) : icon("shield")}<div><h2>${first.chip ? chipNames[first.chip] : "Save chips"}</h2></div></div><ul class="chip-inventory" aria-label="Remaining chips">${Object.keys(
    chipNames,
  )
    .map((c) => {
      const available = team.chips.includes(c) && team.active !== c;
      return `<li class="chip-${c} ${available ? "available" : "spent"}" aria-label="${chipNames[c]}: ${available ? "available" : "spent"}" title="${chipNames[c]}">${chipIcon(c)}</li>`;
    })
    .join(
      "",
    )}</ul><div class="directive-footer">Next chip<span>${nextChip ? `R${nextChip.round} · ${chipNames[nextChip.chip]}` : "None planned"}</span></div></section></div>
   <section class="panel score-panel"><div class="section-heading"><h2>Next race</h2></div><div class="score-comparison"><div class="projected-number"><strong>${points(first.points)}</strong><span>Estimated points</span></div><div><div class="comparison-label"><span>Current team · 2× only</span><strong>${points(reference[0])}</strong></div><div class="comparison-track"><i style="width:${(100 * Math.max(0, reference[0])) / denominator}%"></i></div><div class="comparison-label accent"><span>Suggested team</span><strong>${points(first.points)}</strong></div><div class="comparison-track recommended"><i style="width:${(100 * Math.max(0, first.points)) / denominator}%"></i></div><div class="score-components"><span>Drivers <b>${points(driverScore)}</b></span><span>Constructors <b>${points(constructorScore)}</b></span><span>Penalty <b>−${first.transfer_penalty}</b></span></div></div></div></section>
   <section class="panel horizon"><div class="section-heading"><h2>Season plan</h2><div class="horizon-total"><strong>${points(result.points)} pts</strong></div></div><div class="chart-scroll">${chart(
     result.rounds.map((r) => (cumulative += r.points)),
     result.rounds.map((r) => `R${r.round}`),
   )}</div><div class="round-strip" role="group" aria-label="Choose a planned round">${result.rounds.map((r, i) => `<button data-round="${i}" aria-pressed="${i === selectedRound}"><small>R${r.round} · ${date(r.first_session_utc)}${r.sprint ? " · Sprint" : ""}</small><strong>${esc(shortRace(r.name))}</strong><span class="plan-chip ${r.chip ? `chip-${r.chip}` : "saved-chip"}">${r.chip ? chipIcon(r.chip) : icon("shield")}${r.chip ? chipNames[r.chip] : "Save"}</span><b>${points(r.points)} <small>pts</small></b></button>`).join("")}</div></section>
   ${roundMarkup(dataset, team, round)}`;
}
function roundMarkup(dataset, team, r) {
  // Autopilot's expected extra points are distributed over scenario winners,
  // rather than assigned to the solver's arbitrary nominal Boost variable.
  if (r.chip === "autopilot") r = { ...r, boost: null };
  const max = Math.max(1, ...r.entries.map((e) => Math.abs(e.total)));
  return `<section class="panel round-detail" id="round-detail"><div class="section-heading"><div><h2>R${r.round} · ${esc(shortRace(r.name))}</h2><p>${r.sprint ? "Sprint · " : ""}${r.transfers} transfers${r.chip ? ` · ${chipNames[r.chip]}` : ""}</p></div><div class="round-yield"><strong>${points(r.points)} pts</strong></div></div><div class="split-detail"><div><h3>Changes</h3><div class="transfer-detail"><span class="eyebrow">Out</span>${transferNames(dataset, r.out) || "None"}<span class="transfer-divider">↓</span><span class="eyebrow accent">In</span>${transferNames(dataset, r.in) || "None"}</div>${r.chip === "limitless" ? '<p class="inset-note">Original roster returns after the race.</p>' : ""}</div><div><div class="split-heading"><h3>Points</h3><span><i class="q-key"></i>Qualifying ${r.sprint ? '<i class="s-key"></i>Sprint ' : ""}<i class="r-key"></i>Race</span></div>${r.entries.map((e) => `<div class="yield-row"><div><span>${esc(dataset.assets.find((a) => a.id === e.id).name)}${e.id === r.boost ? ' <b class="tag red">2×</b>' : ""}${e.id === r.x3 ? ' <b class="tag red">3×</b>' : ""}</span><strong>${points(e.total)} pts</strong></div><div class="yield-track" aria-hidden="true">${e.sessions.map((v, i) => `<i class="session-${i}" style="width:${(100 * Math.max(0, v)) / max}%"></i>`).join("")}</div></div>`).join("")}</div></div><div class="table-scroll"><table><caption>Team points</caption><thead><tr><th scope="col">Selection</th><th scope="col">Boost</th><th scope="col">Price</th><th scope="col">Qualifying</th>${r.sprint ? '<th scope="col">Sprint</th>' : ""}<th scope="col">Race</th><th scope="col">Total</th></tr></thead><tbody>${r.entries
    .map((e) => {
      const a = dataset.assets.find((a) => a.id === e.id);
      return `<tr><th scope="row">${esc(a.name)}<small>${a.kind === "DRIVER" ? "Driver" : "Constructor"}</small></th><td>${r.chip === "autopilot" && a.kind === "DRIVER" ? '<span class="tag">Autopilot eligible</span>' : e.id === r.boost ? '<span class="tag red">2× Boost</span>' : e.id === r.x3 ? '<span class="tag red">3× Boost</span>' : "Standard"}</td><td>${money(a.price_tenths_m)}</td><td>${points(e.sessions[0])}</td>${r.sprint ? `<td>${points(e.sessions[1])}</td>` : ""}<td>${points(e.sessions[2])}</td><td><strong>${points(e.total)}</strong></td></tr>`;
    })
    .join(
      "",
    )}</tbody></table></div><div class="round-finances"><span>Value <b>${money(r.cost)}</b> ${r.chip === "limitless" ? "· Limitless" : `/ ${money(team.budget)}`}</span><span>Penalty <b>−${points(r.transfer_penalty)} pts</b></span><span>Carry <b>${r.carry}</b></span></div></section>`;
}
export { insightsMarkup } from "./insights.js";
