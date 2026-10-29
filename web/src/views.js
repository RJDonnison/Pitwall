import { total } from "./optimizer.js";

export const esc = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
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
        `<div class="roster-cards ${kind === "CONSTRUCTOR" ? "constructor-cards" : ""}">${Array.from(
          { length: kind === "DRIVER" ? 5 : 2 },
          (_, i) => {
            const a = dataset.assets.filter(
              (a) => a.kind === kind && team.selected.includes(a.id),
            )[i];
            if (!a)
              return `<a href="#asset-registry" class="roster-empty"><span>+</span><strong>Choose ${kind === "DRIVER" ? "driver" : "constructor"} ${i + 1}</strong><small>Browse the asset registry</small></a>`;
            return `<article class="roster-card" style="--team-color:${teamColor(dataset, a)}"><div class="driver-art">${kind === "DRIVER" ? helmet() : car()}<span>${esc(a.tla || "F1")}</span></div><p class="eyebrow">${esc(constructorName(dataset, a))}</p><h3>${esc(a.name)}</h3><div class="card-numbers"><strong>${money(a.price_tenths_m)}</strong><span>${points(total(round.forecasts[a.id]))}<small>base forecast pts</small></span></div><div class="mini-splits"><span>Q <b>${points(round.forecasts[a.id][0])}</b></span>${round.sprint ? `<span>S <b>${points(round.forecasts[a.id][1])}</b></span>` : ""}<span>R <b>${points(round.forecasts[a.id][2])}</b></span></div><button class="card-action" data-remove="${esc(a.id)}" aria-label="Remove ${esc(a.name)}">Replace selection ${icon("transfer")}</button></article>`;
          },
        ).join("")}</div>`,
    )
    .join("");
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
  return `<section class="panel allocation"><div class="section-heading"><span class="eyebrow">Capital allocation</span><strong>${money(cost)} / ${money(team.budget)}</strong></div><h2>Make every million count.</h2><p>${points((cost / team.budget) * 100)}% of your total cap is allocated. ${free >= 0 ? `${money(free)} remains available.` : `${money(-free)} over cap${team.active === "limitless" ? " · Limitless active" : " · adjust your selections or budget"}.`}</p><div class="allocation-bar" role="img" aria-label="Drivers ${money(drivers)}, constructors ${money(constructors)}, ${free >= 0 ? "free" : "over cap"} ${money(Math.abs(free))}"><span style="width:${width(drivers)}%"></span><span style="width:${width(constructors)}%"></span><span style="width:${width(Math.max(0, free))}%"></span></div><div class="allocation-key"><span><i></i>Drivers<strong>${money(drivers)}</strong></span><span><i></i>Constructors<strong>${money(constructors)}</strong></span><span><i></i>Available<strong class="${free < 0 ? "negative" : ""}">${money(free)}</strong></span></div><p class="inset-note">${icon("shield")}${free >= 0 ? "Within the entered budget" : team.active === "limitless" ? "Temporary uncapped Limitless lineup" : "Above the entered budget"} · manual inputs</p></section>`;
}
function chart(values, labels, cls = "trajectory-chart") {
  const low = Math.min(0, ...values),
    high = Math.max(1, ...values);
  const x = (i) => 40 + (i / Math.max(1, values.length - 1)) * 720;
  const y = (v) => 150 - ((v - low) / (high - low)) * 120;
  return `<svg class="${cls}" viewBox="0 0 800 200" role="img" aria-label="${esc(labels.map((l, i) => `${l}: ${points(values[i])} points`).join(", "))}"><path class="chart-grid" d="M40 30H760M40 90H760M40 150H760"/><polyline class="chart-line" points="${values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>${values.map((v, i) => `<circle class="chart-dot" cx="${x(i)}" cy="${y(v)}" r="4"/><text x="${x(i)}" y="${y(v) - 12}" text-anchor="middle">${points(v)}</text><text class="chart-label" x="${x(i)}" y="184" text-anchor="middle">${esc(labels[i])}</text>`).join("")}</svg>`;
}
export function heroMarkup(dataset, team, result) {
  const r = dataset.rounds[0];
  return `<section class="race-hero"><div class="hero-image"><img src="./racing-editorial.webp" alt="" fetchpriority="high"/><div class="hero-image-shade"></div><span class="race-kicker"><i></i>Round ${r.round} · ${r.sprint ? "Sprint" : "Regular"} weekend</span><div class="hero-copy"><span class="eyebrow">Your season. One joint strategy.</span><h1>${esc(r.name)}</h1><p>Five drivers. Two constructors. A plan for every remaining round, with Boost, chips and net transfers considered together.</p></div></div><div class="hero-outlook"><span class="eyebrow">Season strategy workbench</span><h2>${dataset.rounds.length} rounds.<br>A longer view.</h2><div class="hero-facts"><span><small>Next first session</small><strong>${esc(new Date(r.first_session_utc).toLocaleString())}</strong></span><span><small>Weekend format</small><strong>${r.sprint ? "Qualifying · Sprint · Race" : "Qualifying · Race"}</strong></span></div><div class="hero-bottom"><span>${icon("clock")} First session is not a verified Fantasy lock.</span><a class="button primary" href="#garage">${result ? "Adjust team" : "Build your team"}${icon("arrow")}</a></div></div></section>`;
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
function boostDirective(dataset, round) {
  const automatic = round.chip === "autopilot";
  const driver = dataset.assets.find((a) => a.id === round.boost);
  const entry = round.entries.find((e) => e.id === round.boost);
  const value = automatic
    ? total(round.entries.map((e) => total(e.extra)))
    : entry.total;
  return `<section class="panel directive boost-directive">
    <div class="directive-heading"><span>${icon("bolt")}Regular Boost · next round</span><span class="tag">2×</span></div>
    <div class="boost-visual">${helmet()}<div><span class="eyebrow">${automatic ? "Autopilot chooses after scoring" : "Designated driver"}</span><h2>${automatic ? "Best selected driver" : esc(driver.name)}</h2><p>${automatic ? "Highest total across the whole weekend" : esc(constructorName(dataset, driver))}</p></div></div>
    <div class="boost-output"><strong>${points(value)}</strong><span>${automatic ? "expected extra Boost points" : "forecast pts including 2×"}</span></div>
    <p>${automatic ? "The scoring driver varies across the model’s joint scenarios." : round.x3 ? `Separate 3×: ${esc(dataset.assets.find((a) => a.id === round.x3).name)}.` : "Regular 2× applies to one selected driver."}</p>
    <div class="directive-footer">${round.chip === "no_negative" ? "Includes category-specific No Negative uplift" : "Whole-weekend scoring, including Sprint when present"}</div>
  </section>`;
}
export function strategyMarkup(dataset, team, result, busy, selectedRound) {
  // Presentation summaries distinguish each selection's gross total from the
  // round's net points after transfer penalties.
  if (result)
    result = {
      ...result,
      rounds: result.rounds.map((r) => ({
        ...r,
        transfer_penalty: r.penalty,
        entries: r.entries.map((e) => ({ ...e, total: e.points })),
      })),
    };
  if (!result)
    return `${heroMarkup(dataset, team, result)}<section class="panel welcome"><div class="welcome-symbol">${icon(busy ? "bolt" : "grid")}</div><span class="eyebrow">${busy ? "Exact browser optimization" : "The starting grid is yours"}</span><h2>${busy ? "Working through the possibilities." : "Build your season strategy."}</h2><p>${busy ? "Lineups, transfer timing and chips are being optimized together. A full season can take up to 90 seconds. You can cancel in the Team Garage." : "Add your seven selections in the Team Garage. Set your budget, transfers and remaining chips, then calculate the highest projected total across all remaining rounds."}</p><a class="button primary" href="#garage">${busy ? "View planning progress" : "Open Team Garage"}${icon("arrow")}</a><div class="welcome-key"><span>5 drivers + 2 constructors</span><span>All remaining rounds</span><span>Private, on-device solver</span></div></section>`;
  const first = result.rounds[0],
    round = result.rounds[selectedRound];
  const reference = referencePoints(dataset, team),
    baseline = total(reference);
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
  return `${heroMarkup(dataset, team, result)}<div class="directive-grid"><section class="panel directive"><div class="directive-heading"><span>${icon("transfer")}Roster changes · next round</span><span class="tag">${first.transfer_penalty ? `−${first.transfer_penalty}` : "0"} pts penalty</span></div><h2>${first.transfers} net ${first.transfers === 1 ? "transfer" : "transfers"}</h2><div class="transfer-stack"><div><span class="transfer-badge out">Out</span><div>${transferNames(dataset, first.out) || "No outgoing selections"}</div></div><span class="swap-mark">↕</span><div><span class="transfer-badge">In</span><div>${transferNames(dataset, first.in) || "Keep all seven"}</div></div></div><div class="directive-footer">${first.chip === "limitless" ? "Temporary uncapped lineup" : `Budget remaining: ${money(team.budget - first.cost)}`}<span>${first.chip === "wildcard" || first.chip === "limitless" || team.initial ? "Unlimited changes" : `${2 + team.carry} free allowance`}</span></div></section>${boostDirective(dataset, first)}<section class="panel directive chip-directive"><div class="directive-heading"><span>${icon("shield")}Strategic allocation</span><span class="tag ${first.chip ? "red" : ""}">${first.chip ? "Use chip" : "Hold"}</span></div><div class="chip-callout">${icon("shield")}<div><h2>${first.chip ? chipNames[first.chip] : "Save chips this round"}</h2><p>${first.chip ? chipDescriptions[first.chip] : "Keep available chips for a higher-value round in this season plan."}</p></div></div><div class="chip-dots" aria-label="${team.chips.length} chips marked available">${Object.keys(
    chipNames,
  )
    .map((c) => `<i class="${team.chips.includes(c) ? "available" : ""}"></i>`)
    .join(
      "",
    )}<small>${team.chips.length} of 6 marked available</small></div><div class="directive-footer">Next planned chip<span>${nextChip ? `R${nextChip.round} · ${chipNames[nextChip.chip]}` : "No further pre-weekend chip"}</span></div></section></div>
  <section class="panel score-panel"><div class="section-heading"><div><span class="eyebrow accent">Expected score summary · next round</span><h2>Projected output. Not a promise.</h2></div><span class="tag">Conditional optimality · exact solve</span></div><div class="score-comparison"><div class="projected-number"><strong>${points(first.points)}</strong><span>Fantasy points · after penalties</span><p><b class="${first.points < reference[0] ? "negative" : "positive"}">${delta(first.points - reference[0])} pts</b> versus the unchanged roster with best 2×, without chips.</p></div><div><div class="comparison-label"><span>Unchanged roster · best 2× only</span><strong>${points(reference[0])}</strong></div><div class="comparison-track"><i style="width:${(100 * Math.max(0, reference[0])) / denominator}%"></i></div><div class="comparison-label accent"><span>Recommended roster · Boost + chip</span><strong>${points(first.points)}</strong></div><div class="comparison-track recommended"><i style="width:${(100 * Math.max(0, first.points)) / denominator}%"></i></div><div class="score-components"><span>Drivers <b>${points(driverScore)}</b></span><span>Constructors <b>${points(constructorScore)}</b></span><span>Transfer penalty <b>−${first.transfer_penalty}</b></span></div></div></div></section>
  <section class="panel horizon"><div class="section-heading"><div><span class="eyebrow">Remaining rounds trajectory</span><h2>A championship-length view.</h2></div><div class="horizon-total"><strong>${points(result.points)} pts</strong><small>${delta(result.points - baseline)} vs 2×-only reference</small></div></div><p>Cumulative Fantasy points after transfer penalties. Future prices stay fixed at this snapshot; this is not a confidence interval or FIA championship projection.</p><div class="chart-scroll">${chart(
    result.rounds.map((r) => (cumulative += r.points)),
    result.rounds.map((r) => `R${r.round}`),
  )}</div><div class="round-strip" role="group" aria-label="Choose a planned round">${result.rounds.map((r, i) => `<button data-round="${i}" aria-pressed="${i === selectedRound}"><small>R${r.round} · ${date(r.first_session_utc)}${r.sprint ? " · Sprint" : ""}</small><strong>${esc(shortRace(r.name))}</strong><span class="${r.chip ? "accent" : ""}">${r.chip ? chipNames[r.chip] : "Save chips"}</span><b>${points(r.points)} <small>pts</small></b></button>`).join("")}</div></section>
  ${roundMarkup(dataset, team, round)}<div class="plan-endnote"><span>${icon("shield")}Proven optimal for these forecast inputs and entered rules.</span><button id="replan" class="primary">Recalculate season ${icon("arrow")}</button></div>`;
}
function roundMarkup(dataset, team, r) {
  // Autopilot's expected extra points are distributed over scenario winners,
  // rather than assigned to the solver's arbitrary nominal Boost variable.
  if (r.chip === "autopilot") r = { ...r, boost: null };
  const max = Math.max(1, ...r.entries.map((e) => Math.abs(e.total)));
  return `<section class="panel round-detail" id="round-detail"><div class="section-heading"><div><span class="eyebrow accent">Planned deployment · selected round</span><h2>R${r.round} · ${esc(r.name)}</h2><p>${r.sprint ? "Sprint weekend" : "Regular weekend"} · ${r.chip ? chipNames[r.chip] : "No chip"} · ${r.transfers} net transfers</p></div><div class="round-yield"><strong>${points(r.points)} pts</strong><small>Projected net yield</small></div></div><div class="split-detail"><div><h3>Scheduled market adjustments</h3><div class="transfer-detail"><span class="eyebrow">Move out</span>${transferNames(dataset, r.out) || "No outgoing selections"}<span class="transfer-divider">↓</span><span class="eyebrow accent">Bring in</span>${transferNames(dataset, r.in) || "Keep the existing seven"}</div><div class="inset-note">${icon("shield")}<span>${r.chip ? esc(chipDescriptions[r.chip]) : "No chip is spent this round."} ${r.chip === "limitless" ? "The activation roster is restored afterward." : ""}</span></div></div><div><div class="split-heading"><h3>Selection points yield</h3><span><i class="q-key"></i>Qualifying <i class="s-key"></i>Sprint <i class="r-key"></i>Race</span></div>${r.entries.map((e) => `<div class="yield-row"><div><span>${esc(dataset.assets.find((a) => a.id === e.id).name)}${e.id === r.boost ? ' <b class="tag red">2×</b>' : ""}${e.id === r.x3 ? ' <b class="tag red">3×</b>' : ""}</span><strong>${points(e.total)} pts</strong></div><div class="yield-track" aria-hidden="true">${e.sessions.map((v, i) => `<i class="session-${i}" style="width:${(100 * Math.max(0, v)) / max}%"></i>`).join("")}</div></div>`).join("")}<p class="hint">Positive session contributions shown. Exact signed values are listed below.</p></div></div><div class="table-scroll"><table><caption>All seven selections · predicted Fantasy points including Boost and chip effects</caption><thead><tr><th scope="col">Selection</th><th scope="col">Role</th><th scope="col">Price</th><th scope="col">Qualifying</th>${r.sprint ? '<th scope="col">Sprint</th>' : ""}<th scope="col">Race</th><th scope="col">Total</th></tr></thead><tbody>${r.entries
    .map((e) => {
      const a = dataset.assets.find((a) => a.id === e.id);
      return `<tr><th scope="row">${esc(a.name)}<small>${a.kind === "DRIVER" ? "Driver" : "Constructor"}</small></th><td>${r.chip === "autopilot" && a.kind === "DRIVER" ? '<span class="tag">Autopilot eligible</span>' : e.id === r.boost ? '<span class="tag red">2× Boost</span>' : e.id === r.x3 ? '<span class="tag red">3× Boost</span>' : "Standard"}</td><td>${money(a.price_tenths_m)}</td><td>${points(e.sessions[0])}</td>${r.sprint ? `<td>${points(e.sessions[1])}</td>` : ""}<td>${points(e.sessions[2])}</td><td><strong>${points(e.total)}</strong></td></tr>`;
    })
    .join(
      "",
    )}</tbody></table></div><div class="round-finances"><span>Lineup valuation <b>${money(r.cost)}</b> ${r.chip === "limitless" ? "· temporarily uncapped" : `/ ${money(team.budget)} cap`}</span><span>Penalty <b>−${r.transfer_penalty} pts</b></span><span>Carry forward <b>${r.carry} transfer</b></span></div></section>`;
}
export function insightsMarkup(dataset, team, roundIndex) {
  const r = dataset.rounds[roundIndex];
  const byKind = (kind) =>
    dataset.assets
      .filter((a) => a.kind === kind)
      .sort((a, b) => total(r.forecasts[b.id]) - total(r.forecasts[a.id]));
  const drivers = byKind("DRIVER"),
    constructors = byKind("CONSTRUCTOR");
  const max = Math.max(1, ...drivers.map((a) => total(r.forecasts[a.id])));
  return `<div class="page-heading"><div><span class="eyebrow accent">Published model · Fantasy point estimates</span><h1>Forecast explorer</h1><p>Compare the grid for ${esc(r.name)}. These are Fantasy scores, not predicted finishing positions or FIA championship points.</p></div><label>Forecast round<select id="insights-round">${dataset.rounds.map((r, i) => `<option value="${i}" ${i === roundIndex ? "selected" : ""}>R${r.round} · ${esc(shortRace(r.name))}</option>`).join("")}</select></label></div><div class="insights-grid"><section class="panel"><div class="section-heading"><div><span class="eyebrow accent">Driver output · unboosted</span><h2>The whole weekend, broken down.</h2></div></div><div class="forecast-bars">${drivers.map((a) => `<div class="forecast-bar"><div><span><b class="tla" style="--team-color:${teamColor(dataset, a)}">${esc(a.tla || "F1")}</b><strong>${esc(a.name)}</strong><small>${esc(constructorName(dataset, a))}</small></span><strong>${points(total(r.forecasts[a.id]))} pts</strong></div><div class="yield-track" aria-hidden="true">${r.forecasts[a.id].map((v, i) => `<i class="session-${i}" style="width:${(100 * Math.max(0, v)) / max}%"></i>`).join("")}</div><p>Q ${points(r.forecasts[a.id][0])}${r.sprint ? ` · Sprint ${points(r.forecasts[a.id][1])}` : ""} · Race ${points(r.forecasts[a.id][2])} · ${money(a.price_tenths_m)}</p></div>`).join("")}</div></section><aside><section class="panel"><span class="eyebrow">Asset efficiency · drivers</span><h2>Points per million</h2><p>Base forecast divided by today's price. Efficiency alone does not determine the optimal seven.</p>${byKind(
    "DRIVER",
  )
    .sort(
      (a, b) =>
        total(r.forecasts[b.id]) / b.price_tenths_m -
        total(r.forecasts[a.id]) / a.price_tenths_m,
    )
    .slice(0, 5)
    .map(
      (a) =>
        `<div class="efficiency-row"><strong>${esc(a.name)}</strong><b>${points(total(r.forecasts[a.id]) / (a.price_tenths_m / 10))}</b></div>`,
    )
    .join(
      "",
    )}</section><section class="panel roadmap-note"><span class="eyebrow accent">Race Insights · V6</span><h2>The next layer is on the roadmap.</h2><p>Race probabilities, fastest pit stops and championship projections are not part of this Fantasy forecast view. Weather modeling is planned separately for V8.</p><a class="button" href="#garage">Use these forecasts ${icon("arrow")}</a></section></aside></div><section class="constructor-section"><div class="section-heading"><div><span class="eyebrow accent">Constructor forecast matrix</span><h2>Two cars. One selection.</h2></div><span class="tag">Base scores · no chip or Boost</span></div><div class="constructor-grid">${constructors.map((a) => `<article class="panel constructor-card" style="--team-color:${teamColor(dataset, a)}"><span class="eyebrow">${money(a.price_tenths_m)}</span><h3>${esc(a.name)}</h3><strong class="constructor-score">${points(total(r.forecasts[a.id]))}<small> predicted pts</small></strong>${car()}<div class="mini-splits"><span>Q <b>${points(r.forecasts[a.id][0])}</b></span>${r.sprint ? `<span>S <b>${points(r.forecasts[a.id][1])}</b></span>` : ""}<span>R <b>${points(r.forecasts[a.id][2])}</b></span></div></article>`).join("")}</div></section>`;
}
