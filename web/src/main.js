import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./style.css";
import { CHIPS, PREWEEK, total, validateTeam } from "./optimizer.js";
import { fetchDataset, verifyLive } from "./data.js";
import {
  esc,
  points,
  money,
  chipNames,
  chipDescriptions,
  icon,
  constructorName,
  teamColor,
  profilesMarkup,
  rosterMarkup,
  allocationMarkup,
  strategyMarkup,
  insightsMarkup,
} from "./views.js";

const $ = (query) => document.querySelector(query);
const blank = (i) => ({
  name: `Team ${i + 1}`,
  season: null,
  selected: [],
  budget: 1000,
  carry: 0,
  chips: [...CHIPS],
  completed: true,
  initial: false,
  allowPenalties: false,
  active: "",
  restore: [],
});
function parseMoney(value) {
  const amount = Number(value) * 10;
  if (
    !Number.isFinite(amount) ||
    amount <= 0 ||
    Math.abs(amount - Math.round(amount)) > 1e-6
  )
    throw new Error(
      "Enter a positive total budget with at most one decimal place.",
    );
  return Math.round(amount);
}
let profiles;
try {
  const stored = JSON.parse(localStorage.getItem("pitwall-teams-v1"));
  profiles =
    Array.isArray(stored) &&
    stored.length === 3 &&
    stored.every(
      (t) =>
        t &&
        typeof t.name === "string" &&
        Array.isArray(t.selected) &&
        Array.isArray(t.chips) &&
        Array.isArray(t.restore) &&
        Number.isInteger(t.budget) &&
        [0, 1].includes(t.carry),
    )
      ? stored.map((t, i) => ({ ...blank(i), ...t }))
      : [blank(0), blank(1), blank(2)];
} catch {
  profiles = [blank(0), blank(1), blank(2)];
}
let active = 0,
  dataset = null,
  result = null,
  marketRound = 0,
  insightsRound = 0,
  selectedRound = 0,
  marketKind = "ALL",
  worker = null,
  error = "",
  busy = false,
  verification = "",
  previewAllowed = false,
  revision = 0;
const team = () => profiles[active];
const asset = (id) => dataset.assets.find((a) => a.id === id);
function save() {
  try {
    localStorage.setItem("pitwall-teams-v1", JSON.stringify(profiles));
  } catch {
    error =
      "Browser storage is unavailable. Export your team before leaving this page.";
  }
}
function invalidate() {
  revision++;
  worker?.terminate();
  worker = null;
  busy = false;
  result = null;
  selectedRound = 0;
  error = "";
  save();
}
function switchTeam(i) {
  invalidate();
  active = i;
  verification = "";
  render();
}
function route() {
  const name = location.hash.slice(1);
  const page =
    name === "garage" || name === "asset-registry"
      ? "garage"
      : name === "insights"
        ? "insights"
        : "strategy";
  for (const p of ["strategy", "garage", "insights"])
    $(`#page-${p}`).hidden = p !== page;
  document
    .querySelectorAll("[data-nav]")
    .forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === page));
  document
    .querySelectorAll("[data-nav][aria-current]")
    .forEach((a) => a.setAttribute("aria-current", "page"));
  if (name === "asset-registry")
    $("#asset-registry").scrollIntoView({ block: "start" });
  else if (name === "how-it-works")
    $("#how-it-works").scrollIntoView({ block: "start" });
}
function openGarage() {
  location.hash = "garage";
  route();
}
function shell() {
  $("#app").innerHTML =
    `<a class="skip-link" href="#main">Skip to content</a><header class="masthead"><div class="header-inner"><a class="brand" href="#strategy"><span class="brand-mark" aria-hidden="true">╲</span><span><strong>Pitwall</strong><small>Independent F1 Fantasy planning</small></span></a><nav aria-label="Main navigation"><a href="#strategy" data-nav="strategy">Strategy</a><a href="#garage" data-nav="garage">Team Garage</a><a href="#insights" data-nav="insights">Forecasts</a><a href="#how-it-works">How it works</a></nav><div class="header-tools"><span id="header-cap" class="cap-tag">Loading the grid</span><label class="team-switch">${icon("grid")}<span class="sr-only">Active team</span><select id="team-switch"></select></label></div></div></header>
  <main id="main"><div id="data-state" class="data-state" role="status">Fetching the latest published forecasts…</div><section id="page-strategy" aria-label="Season strategy"><div id="strategy"></div></section>
  <section id="page-garage" aria-label="Team Garage" hidden><div class="page-heading"><div><span class="eyebrow accent">Paddock lineup engineering · local device storage</span><h1>Team Garage</h1><p>Set your starting seven. Build the strategy around your actual budget and chips.</p></div><a class="button" href="#strategy">View season strategy ${icon("arrow")}</a></div><div id="profile-cards" class="profile-grid" role="group" aria-label="Saved teams"></div><div class="garage-workspace"><div class="garage-main"><div id="allocation"></div><section id="roster-board" aria-label="Starting roster"></section><section class="market" id="asset-registry"><div class="section-heading"><div><span class="eyebrow">Market asset registry</span><h2>Find the right seven.</h2><p>Base Fantasy point forecasts. Prices are in millions.</p></div><label>Forecast round<select id="market-round" aria-label="Round for grid forecasts"></select></label></div><div class="market-tools"><div class="segments" role="group" aria-label="Asset type"><button id="all-tab" data-kind="ALL" aria-pressed="true">All targets</button><button id="drivers-tab" data-kind="DRIVER" aria-pressed="false">Drivers</button><button id="constructors-tab" data-kind="CONSTRUCTOR" aria-pressed="false">Constructors</button></div><input id="search" type="search" aria-label="Search drivers and constructors" placeholder="Search the grid…"/></div><div id="market-list" class="market-cards"></div></section></div><aside class="editor" aria-label="Team settings and chip inventory"><div id="settings"></div></aside></div></section>
  <section id="page-insights" aria-label="Fantasy forecast explorer" hidden><div id="insights"></div></section>
  <section id="how-it-works" class="method"><span class="eyebrow accent">Strategic principle</span><h2>Think in seasons. Check before you change.</h2><div class="method-grid"><article><h3>One joint plan <small>Optimizer</small></h3><p>An exact mixed-integer optimizer runs on your device. It considers five drivers, two constructors, 2× Boost, once-per-season chips, Sprint weekends, net transfers and their penalties across all published remaining rounds.</p><a href="https://fantasy.formula1.com/en/game-rules" target="_blank" rel="noopener noreferrer">Official Fantasy rules ↗</a></article><article><h3>Forecasts, not promises <small>Model</small></h3><p>Historical inputs precede the predicted weekend. Future prices stay at today’s snapshot. Re-plan as prices, results and your team change. Final Fix needs a separate post-qualifying decision; it has no speculative pre-weekend value here.</p></article><article><h3>Your teams stay here <small>Privacy</small></h3><p>Three profiles are stored in this browser. There is no account sign-in, server-side team storage or automatic submission. Published data is a preview; check official prices, eligibility and lock before making changes.</p></article></div></section></main><footer><span><b>Pitwall</b> · Independent F1 Fantasy planning</span><span>Decorative racing imagery from your Stitch mockup. Not affiliated with Formula 1.</span></footer>`;
  $("#team-switch").onchange = (e) => switchTeam(Number(e.target.value));
  $("#market-round").onchange = (e) => {
    marketRound = Number(e.target.value);
    renderMarket();
  };
  $("#search").oninput = renderMarket;
  document.querySelectorAll("[data-kind]").forEach(
    (b) =>
      (b.onclick = () => {
        marketKind = b.dataset.kind;
        renderMarket();
      }),
  );
  addEventListener("hashchange", route);
  route();
}
function render() {
  const focused = document.activeElement?.id;
  const advancedOpen = $("#active-setup")?.open || Boolean(team().active);
  $("#team-switch").innerHTML = profiles
    .map(
      (t, i) =>
        `<option value="${i}" ${active === i ? "selected" : ""}>${esc(t.name)}</option>`,
    )
    .join("");
  if (!dataset) {
    $("#market-list").innerHTML = "";
    $("#market-round").innerHTML = "";
    $("#profile-cards").innerHTML = "";
    $("#allocation").innerHTML = "";
    $("#roster-board").innerHTML = "";
    $("#header-cap").textContent = "Awaiting verified inputs";
    const message = `<div class="panel welcome"><span class="eyebrow">Public forecast publication</span><h2>Waiting for the grid.</h2><p>${esc(error || "Loading public roster and forecasts…")}</p><button data-reload class="primary">Refresh data</button></div>`;
    $("#strategy").innerHTML = message;
    $("#insights").innerHTML = message;
    $("#settings").innerHTML = message;
    document
      .querySelectorAll("[data-reload]")
      .forEach((b) => (b.onclick = load));
    return;
  }
  const t = team(),
    chosen = dataset.assets.filter((a) => t.selected.includes(a.id)),
    cost = total(chosen.map((a) => a.price_tenths_m));
  $("#header-cap").innerHTML =
    `Cap <b>${money(cost)}</b> / ${money(t.budget)} <strong class="${cost > t.budget ? "negative" : "positive"}">${money(t.budget - cost)} free</strong>`;
  $("#data-state").innerHTML =
    `<div><span class="data-dot"></span><strong>Planning preview</strong><span>${esc(verification || "Manual team inputs · published prices, not a verified account")}</span></div><div><small>Prices checked ${esc(new Date(dataset.price_checked_at).toLocaleString())} · expires after 6h</small><button id="refresh">Refresh data</button></div>`;
  $("#refresh").onclick = () => {
    invalidate();
    load();
  };
  $("#profile-cards").innerHTML = profilesMarkup(dataset, profiles, active);
  document
    .querySelectorAll("[data-team]")
    .forEach((b) => (b.onclick = () => switchTeam(Number(b.dataset.team))));
  $("#allocation").innerHTML = allocationMarkup(dataset, t);
  $("#roster-board").innerHTML =
    `<div class="section-heading"><div><span class="eyebrow">Active roster assets</span><h2>Your starting seven</h2><p>Use your original race-week lineup for net transfers.</p></div><span class="tag">${chosen.filter((a) => a.kind === "DRIVER").length}/5 drivers · ${chosen.filter((a) => a.kind === "CONSTRUCTOR").length}/2 constructors</span></div>${rosterMarkup(dataset, t, dataset.rounds[0])}`;
  $("#settings").innerHTML =
    `<div class="panel editor-body"><div class="section-heading"><div><span class="eyebrow accent">Strategy parameters</span><h2>Your balance sheet</h2></div>${icon("grid")}</div><label>Team name<input id="team-name" maxlength="32" value="${esc(t.name)}"/></label><div class="form-grid"><label>Total budget ($m)<input id="budget" type="number" min="0.1" step="0.1" value="${t.budget / 10}" aria-describedby="budget-help"/></label><label>Carried transfer<select id="carry"><option value="0" ${t.carry === 0 ? "selected" : ""}>0 · 2 free</option><option value="1" ${t.carry === 1 ? "selected" : ""}>1 · 3 free</option></select></label></div><p class="hint" id="budget-help">Total team value + cash, not just your bank balance.</p>
  <label class="check"><input type="checkbox" id="initial" ${t.initial ? "checked" : ""}/>My team has not scored a race yet</label><label class="check"><input type="checkbox" id="completed" ${t.completed ? "checked" : ""}/>I have completed a full race weekend</label><label class="check"><input type="checkbox" id="penalties" ${t.allowPenalties ? "checked" : ""}/>Allow paid transfers when worth −10 points each</label>
  <fieldset class="chips"><legend>Chips still available</legend>${CHIPS.map(
    (c) => {
      const supported = dataset.chip_support[c]?.available !== false;
      return `<label class="chip-option" title="${esc(chipDescriptions[c])}"><input id="chip-${c}" type="checkbox" data-chip="${c}" ${t.chips.includes(c) ? "checked" : ""} ${!supported ? "disabled" : ""}/><span>${chipNames[c]}<small>${supported ? (c === "final_fix" ? "After qualifying · separate decision" : "Once this season") : "History unavailable"}</small></span>${icon(c === "x3" || c === "autopilot" ? "bolt" : "shield")}</label>`;
    },
  ).join("")}</fieldset>
  <details class="advanced" id="active-setup" ${advancedOpen ? "open" : ""}><summary>Already activated a chip?</summary><label>Active this weekend<select id="active-chip"><option value="">None</option>${PREWEEK.map((c) => `<option value="${c}" ${t.active === c ? "selected" : ""}>${chipNames[c]}</option>`).join("")}</select></label>${
    t.active === "limitless"
      ? `<label>Team restored after Limitless<select id="restore" multiple size="7">${[
          "DRIVER",
          "CONSTRUCTOR",
        ]
          .map(
            (kind) =>
              `<optgroup label="${kind === "DRIVER" ? "Choose five drivers" : "Choose two constructors"}">${dataset.assets
                .filter((a) => a.kind === kind)
                .map(
                  (a) =>
                    `<option value="${esc(a.id)}" ${t.restore.includes(a.id) ? "selected" : ""}>${esc(a.name)}</option>`,
                )
                .join("")}</optgroup>`,
          )
          .join(
            "",
          )}</select></label><p class="hint">Select the original seven using Ctrl/Cmd. Required for full-season restoration.</p>`
      : '<p class="hint">An active chip retains its effect even if removed from remaining inventory. Final Fix is a separate remaining-session decision.</p>'
  }</details>
  <div class="import-export"><button id="export-team">Export team</button><label class="file-button">Import team<input type="file" id="import-team" accept="application/json,.json"/></label></div><label class="check preview-consent"><input type="checkbox" id="preview-consent" ${previewAllowed ? "checked" : ""}/>Allow a published-snapshot preview if live prices cannot be verified</label><button id="optimize" class="primary full-width" ${busy ? "disabled" : ""}>${busy ? "Planning the season…" : "Calculate season strategy"}${icon("arrow")}</button>${busy ? '<button id="cancel" class="full-width">Cancel planning</button>' : ""}<p id="editor-error" class="error" role="alert" tabindex="-1">${esc(error)}</p><p class="hint">Changes clear your plan. Enter substitutions manually in the official game.</p></div>`;
  for (const id of [
    "budget",
    "carry",
    "initial",
    "completed",
    "penalties",
    "active-chip",
  ])
    $(`#${id}`).onchange = () => {
      const value = $(`#${id}`);
      if (id === "budget") {
        try {
          parseMoney(value.value);
        } catch (e) {
          invalidate();
          error = e.message;
          render();
          return;
        }
      }
      const key = {
        budget: "budget",
        carry: "carry",
        initial: "initial",
        completed: "completed",
        penalties: "allowPenalties",
        "active-chip": "active",
      }[id];
      t[key] =
        value.type === "checkbox"
          ? value.checked
          : id === "budget"
            ? parseMoney(value.value)
            : id === "carry"
              ? Number(value.value)
              : value.value;
      if (t.initial) {
        t.carry = 0;
        t.completed = false;
      }
      invalidate();
      render();
    };
  $("#team-name").onchange = (e) => {
    t.name = e.target.value.trim() || `Team ${active + 1}`;
    save();
    render();
  };
  document.querySelectorAll("[data-remove]").forEach(
    (b) =>
      (b.onclick = () => {
        t.selected = t.selected.filter((id) => id !== b.dataset.remove);
        invalidate();
        render();
      }),
  );
  document.querySelectorAll("[data-chip]").forEach(
    (c) =>
      (c.onchange = () => {
        t.chips = c.checked
          ? [...t.chips, c.dataset.chip]
          : t.chips.filter((id) => id !== c.dataset.chip);
        invalidate();
        render();
      }),
  );
  if ($("#restore"))
    $("#restore").onchange = (e) => {
      t.restore = Array.from(e.target.selectedOptions, (o) => o.value);
      invalidate();
      render();
    };
  $("#preview-consent").onchange = (e) => {
    previewAllowed = e.target.checked;
  };
  $("#optimize").onclick = plan;
  if ($("#cancel"))
    $("#cancel").onclick = () => {
      invalidate();
      render();
    };
  $("#export-team").onclick = exportTeam;
  $("#import-team").onchange = importTeam;
  $("#market-round").innerHTML = dataset.rounds
    .map(
      (r, i) =>
        `<option value="${i}" ${i === marketRound ? "selected" : ""}>R${r.round} · ${esc(r.name.replace(" Grand Prix", ""))}</option>`,
    )
    .join("");
  renderStrategy();
  renderMarket();
  renderInsights();
  route();
  if (focused && document.getElementById(focused))
    document.getElementById(focused).focus({ preventScroll: true });
}
function renderMarket() {
  if (!dataset) return;
  document
    .querySelectorAll("[data-kind]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(marketKind === b.dataset.kind)),
    );
  const query = $("#search").value.toLowerCase(),
    r = dataset.rounds[marketRound];
  const available = dataset.assets
    .filter(
      (a) =>
        (marketKind === "ALL" || a.kind === marketKind) &&
        `${a.name} ${constructorName(dataset, a)}`
          .toLowerCase()
          .includes(query),
    )
    .sort((a, b) => total(r.forecasts[b.id]) - total(r.forecasts[a.id]));
  $("#market-list").innerHTML =
    available
      .map((a) => {
        const selected = team().selected.includes(a.id),
          count = team().selected.filter(
            (id) => asset(id)?.kind === a.kind,
          ).length;
        return `<article class="market-card ${selected ? "selected" : ""}" style="--team-color:${teamColor(dataset, a)}"><div class="market-card-title"><span class="asset-monogram">${esc(a.tla || "F1")}</span><div><h3>${esc(a.name)}</h3><small>${esc(constructorName(dataset, a))}</small></div><strong>${money(a.price_tenths_m)}</strong></div><div class="market-splits"><span>Q ${points(r.forecasts[a.id][0])}</span>${r.sprint ? `<span>S ${points(r.forecasts[a.id][1])}</span>` : ""}<span>R ${points(r.forecasts[a.id][2])}</span></div><div class="market-card-bottom"><span>Projected <b>${points(total(r.forecasts[a.id]))} pts</b></span><button data-select="${esc(a.id)}" aria-label="${selected ? "Remove" : "Add"} ${esc(a.name)}" aria-pressed="${selected}" ${!selected && count >= (a.kind === "DRIVER" ? 5 : 2) ? "disabled" : ""}>${selected ? "− Remove" : "+ Add"}</button></div></article>`;
      })
      .join("") ||
    '<p class="empty">No matching selections. Try another name.</p>';
  document.querySelectorAll("[data-select]").forEach(
    (b) =>
      (b.onclick = () => {
        const id = b.dataset.select;
        team().selected = team().selected.includes(id)
          ? team().selected.filter((key) => key !== id)
          : [...team().selected, id];
        invalidate();
        render();
      }),
  );
}
function renderStrategy() {
  $("#strategy").innerHTML = strategyMarkup(
    dataset,
    team(),
    result,
    busy,
    selectedRound,
  );
  document.querySelectorAll("[data-round]").forEach(
    (b) =>
      (b.onclick = () => {
        selectedRound = Number(b.dataset.round);
        renderStrategy();
        $(`[data-round="${selectedRound}"]`).focus({ preventScroll: true });
      }),
  );
  if ($("#replan")) $("#replan").onclick = plan;
}
function renderInsights() {
  $("#insights").innerHTML = insightsMarkup(dataset, team(), insightsRound);
  $("#insights-round").onchange = (e) => {
    insightsRound = Number(e.target.value);
    renderInsights();
    $("#insights-round").focus({ preventScroll: true });
  };
}
async function load() {
  const request = ++revision;
  error = "";
  dataset = null;
  result = null;
  render();
  try {
    const fresh = await fetchDataset();
    if (request !== revision) return;
    dataset = fresh;
    marketRound = 0;
    insightsRound = 0;
    selectedRound = 0;
    for (const t of profiles) {
      if (t.season !== null && t.season !== dataset.season) {
        t.selected = [];
        t.chips = [...CHIPS];
        t.active = "";
        t.restore = [];
      }
      t.season = dataset.season;
      t.chips = t.chips.filter(
        (c) => dataset.chip_support[c]?.available !== false,
      );
    }
    save();
  } catch (e) {
    if (request !== revision) return;
    error = e.message;
    $("#data-state").textContent = error;
  }
  render();
}
async function plan() {
  if (busy) return;
  try {
    validateTeam(dataset, team());
  } catch (e) {
    error = e.message;
    render();
    openGarage();
    $("#editor-error").focus();
    return;
  }
  busy = true;
  error = "";
  result = null;
  selectedRound = 0;
  render();
  const profile = active,
    request = ++revision;
  try {
    const fresh = await fetchDataset();
    if (!busy || profile !== active || request !== revision) return;
    if (JSON.stringify(fresh) !== JSON.stringify(dataset)) {
      dataset = fresh;
      throw new Error(
        "New forecasts have arrived. Check the updated grid and run your plan again.",
      );
    }
    const check = await verifyLive(fresh);
    if (!busy || profile !== active || request !== revision) return;
    verification = check.message;
    if (!check.verified && !previewAllowed)
      throw new Error(
        "Live prices cannot be verified. Tick the published-snapshot preview option to continue, or use the Python CLI with live feeds.",
      );
    worker = new Worker(new URL("./worker.js", import.meta.url), {
      type: "module",
    });
    worker.onmessage = ({ data }) => {
      if (request !== revision) return;
      worker.terminate();
      worker = null;
      busy = false;
      result = data.result || null;
      error = data.error || "";
      render();
      if (result) {
        location.hash = "strategy";
        route();
        $("#strategy h1").setAttribute("tabindex", "-1");
        $("#strategy h1").focus({ preventScroll: true });
        window.scrollTo({ top: 0, behavior: "instant" });
      } else {
        openGarage();
        $("#editor-error").focus();
      }
    };
    worker.onerror = () => {
      if (request !== revision) return;
      worker?.terminate();
      worker = null;
      busy = false;
      error =
        "The browser solver failed to load. Refresh or try a WebAssembly-capable browser.";
      render();
      openGarage();
      $("#editor-error").focus();
    };
    worker.postMessage({ dataset: fresh, team: structuredClone(team()) });
  } catch (e) {
    if (request !== revision) return;
    busy = false;
    error = e.message;
    render();
    openGarage();
    $("#editor-error").focus();
  }
}
function exportTeam() {
  const t = team();
  const payload = {
    season: dataset.season,
    name: t.name,
    drivers: t.selected.filter((id) => asset(id)?.kind === "DRIVER"),
    constructors: t.selected.filter((id) => asset(id)?.kind === "CONSTRUCTOR"),
    budget: t.budget / 10,
    carry: t.carry,
    available_chips: t.chips,
    completed_first_weekend: t.completed,
    unlimited_transfers: t.initial,
    active_chip: t.active || null,
    limitless_restoration_ids: t.restore,
    allow_penalties: t.allowPenalties,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "pitwall-team.json";
  a.click();
  URL.revokeObjectURL(url);
}
async function importTeam(e) {
  const profile = active,
    request = revision;
  try {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 100000)
      throw new Error("Team import must be smaller than 100 KB.");
    const raw = JSON.parse(await file.text());
    if (profile !== active || request !== revision) return;
    const value = raw.data || raw;
    if (
      value.season !== dataset.season ||
      !Array.isArray(value.drivers) ||
      !Array.isArray(value.constructors)
    )
      throw new Error(
        "Import must contain this season, five drivers and two constructors.",
      );
    const imported = {
      ...blank(active),
      name:
        typeof value.name === "string" ? value.name.slice(0, 32) : team().name,
      season: value.season,
      selected: [...value.drivers, ...value.constructors].map(String),
      budget: value.budget_tenths_m ?? parseMoney(value.budget),
      carry: value.carry ?? 0,
      chips: value.available_chips ?? [],
      active: value.active_chip || "",
      completed:
        value.completed_first_weekend === true ||
        value.eligible_chips?.includes("wildcard") === true,
      initial:
        value.unlimited_transfers === true &&
        !["wildcard", "limitless"].includes(value.active_chip),
      restore: (value.limitless_restoration_ids || []).map(String),
      allowPenalties: value.allow_penalties === true,
    };
    validateTeam(dataset, imported);
    invalidate();
    profiles[active] = imported;
    save();
    render();
  } catch (e) {
    error = `Cannot import team: ${e.message}`;
    render();
  }
}
shell();
render();
load();
