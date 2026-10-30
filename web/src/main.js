import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./style.css";
import "./insight-visuals.css";
import "./participant-browser.css";
import {
  CHIPS,
  PREWEEK,
  total,
  validateTeam,
  validateDataset,
} from "./optimizer.js";
import { fetchDataset, verifyLive } from "./data.js";
import { suggestionRequest } from "./team-suggestion.js";
import {
  esc,
  money,
  chipNames,
  chipDescriptions,
  icon,
  constructorName,
  registryCardMarkup,
  profilesMarkup,
  rosterMarkup,
  allocationMarkup,
  strategyMarkup,
  insightsMarkup,
} from "./views.js";
import { logo, chipIcon, footerMarkup } from "./visuals.js";
import {
  rememberWeekend,
  weekendReady,
  adoptWeekend,
} from "./team-progress.js";

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
  allowPenalties: true,
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
    stored.length > 0 &&
    stored
      .slice(0, 3)
      .every(
        (t) =>
          t &&
          typeof t.name === "string" &&
          Array.isArray(t.selected) &&
          Array.isArray(t.chips) &&
          Array.isArray(t.restore) &&
          Number.isInteger(t.budget) &&
          [0, 1].includes(t.carry),
      )
      ? (() => {
          try {
            if (
              stored.length > 3 &&
              !localStorage.getItem("pitwall-teams-before-three-slot-limit")
            )
              localStorage.setItem(
                "pitwall-teams-before-three-slot-limit",
                JSON.stringify(stored),
              );
          } catch {
            /* Retain readable profiles even if backup storage is full. */
          }
          return Array.from({ length: 3 }, (_, i) => ({
            ...blank(i),
            ...stored[i],
          }));
        })()
      : [blank(0), blank(1), blank(2)];
} catch {
  profiles = [blank(0), blank(1), blank(2)];
}
let active = 0,
  dataset = null,
  result = null,
  selectedRound = 0,
  marketKind = "ALL",
  marketSort = "price-desc",
  worker = null,
  error = "",
  busy = false,
  planningTimer = null,
  verificationText = "Price snapshot",
  revision = 0;
const insightState = {
  population: "drivers",
  round: null,
  metric: "win",
  entity: null,
  participantQuery: "",
};
const team = () => profiles[active];
function save() {
  try {
    localStorage.setItem("pitwall-teams-v1", JSON.stringify(profiles));
  } catch {
    error =
      "Browser storage is unavailable. Export your team before leaving this page.";
  }
}
function invalidate() {
  clearTimeout(planningTimer);
  revision++;
  worker?.terminate();
  worker = null;
  busy = false;
  result = null;
  selectedRound = 0;
  error = "";
  save();
  queuePlan();
}
function queuePlan() {
  clearTimeout(planningTimer);
  if (!dataset || team().selected.length !== 7) return;
  planningTimer = setTimeout(plan, 700);
}
function switchTeam(i) {
  invalidate();
  active = i;
  queuePlan();
  render();
}
function suggestTeam() {
  if (!dataset || busy) return;
  invalidate();
  clearTimeout(planningTimer);
  plan({ fill: true });
}
function route({ scroll = false } = {}) {
  const name = location.hash.slice(1);
  if (name === "main") return;
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
  if (scroll && name === "asset-registry")
    $("#asset-registry").scrollIntoView({ block: "start" });
  else if (scroll && name === "image-credits") {
    $("#image-credits").open = true;
    $("#image-credits").scrollIntoView({ block: "start" });
  }
}
function shell() {
  $("#app").innerHTML =
    `<a class="skip-link" href="#main">Skip to content</a><header class="masthead"><div class="header-inner"><a class="brand" href="#strategy" aria-label="Pitwall home">${logo()}<strong>Pitwall</strong></a><nav aria-label="Main navigation"><a href="#garage" data-nav="garage">Garage</a><a href="#insights" data-nav="insights">Race Insights</a></nav><div class="header-tools"><span id="header-cap" class="cap-tag">Loading…</span><label class="team-switch"><span class="sr-only">Active team</span><select id="team-switch"></select></label></div></div></header>
     <main id="main"><section id="page-strategy" aria-label="Season strategy"><div id="strategy"></div></section><section id="page-garage" aria-label="Garage" hidden><div class="page-heading garage-heading"><div><h1>Garage</h1><span id="planning-status" role="status"></span></div><button type="button" id="new-team">Suggest team</button></div><div id="profile-cards" class="profile-grid" role="group" aria-label="Saved teams"></div><section id="settings" aria-label="Budget, transfers and chips"></section><div id="allocation"></div><section id="roster-board" aria-label="Starting roster"></section><section class="market" id="asset-registry"><div class="section-heading"><h2>Asset Registry</h2></div><div class="market-tools"><input id="search" type="search" aria-label="Search drivers and constructors" placeholder="Search driver or constructor…"/><div class="segments" role="group" aria-label="Asset type"><button id="all-tab" data-kind="ALL" aria-pressed="true">All</button><button id="drivers-tab" data-kind="DRIVER" aria-pressed="false">Drivers</button><button id="constructors-tab" data-kind="CONSTRUCTOR" aria-pressed="false">Constructors</button></div></div><div id="market-list" class="market-cards"></div></section></section><section id="page-insights" aria-label="Race Insights" hidden><div id="insights"></div></section></main>${footerMarkup()}`;
  $("#new-team").onclick = suggestTeam;
  $(".market-tools").insertAdjacentHTML(
    "beforeend",
    '<label class="market-sort">Sort by<select id="market-sort"><option value="price-desc">Price: high to low</option><option value="price-asc">Price: low to high</option><option value="points">Projected points</option><option value="value">Points per $m</option><option value="name">Name: A–Z</option></select></label>',
  );
  $("#market-sort").onchange = (e) => {
    marketSort = e.target.value;
    renderMarket();
  };
  $("#team-switch").onchange = (e) => switchTeam(Number(e.target.value));
  $("#search").oninput = renderMarket;
  document.querySelectorAll("[data-kind]").forEach(
    (b) =>
      (b.onclick = () => {
        marketKind = b.dataset.kind;
        renderMarket();
      }),
  );
  addEventListener("hashchange", () => route({ scroll: true }));
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.insertAdjacentHTML(
      "afterbegin",
      icon(link.dataset.nav === "garage" ? "grid" : "bolt"),
    );
  });
  route({ scroll: true });
}
function render() {
  $("#new-team").disabled = busy || !dataset;
  $("#new-team").title =
    "Replace this slot's roster with the best next-round lineup within its budget, including the 2× Boost. Available chips are kept for season planning.";
  const focused = document.activeElement?.id;
  const focusedChip = document.activeElement?.dataset.chip;
  const advancedOpen = $("#active-setup")?.open || Boolean(team().active);
  $("#team-switch").innerHTML = profiles
    .map(
      (t, i) =>
        `<option value="${i}" ${active === i ? "selected" : ""}>${esc(t.name)}</option>`,
    )
    .join("");
  if (!dataset) {
    $("#market-list").innerHTML = "";
    $("#profile-cards").innerHTML = "";
    $("#allocation").innerHTML = "";
    $("#roster-board").innerHTML = "";
    $("#header-cap").textContent = "Awaiting verified inputs";
    const message = `<div class="panel welcome"><h2>${error ? "Forecasts unavailable" : "Loading…"}</h2><p>${esc(error || "Fetching the latest publication.")}</p></div>`;
    $("#strategy").innerHTML = message;
    $("#insights").innerHTML = message;
    $("#settings").innerHTML = message;
    return;
  }
  const t = team(),
    chosen = dataset.assets.filter((a) => t.selected.includes(a.id)),
    cost = total(chosen.map((a) => a.price_tenths_m));
  $("#header-cap").innerHTML =
    `Cap <b>${money(cost)}</b> / ${money(t.budget)} <strong class="${cost > t.budget ? "negative" : "positive"}">${money(t.budget - cost)} free</strong>`;
  $("#publication-status").textContent =
    `${verificationText} · ${new Date(dataset.price_checked_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC`;
  $("#publication-window").textContent =
    `Published ${new Date(dataset.generated_at).toLocaleString()} · valid for new plans until ${new Date(Date.parse(dataset.generated_at) + 6 * 60 * 60 * 1000).toLocaleString()}.`;
  $("#planning-status").textContent = busy
    ? "Updating strategy…"
    : result
      ? "Strategy up to date"
      : error
        ? "Check team settings"
        : t.selected.length === 7
          ? "Strategy updates automatically"
          : "Choose five drivers and two constructors";
  $("#profile-cards").innerHTML = profilesMarkup(dataset, profiles, active);
  document
    .querySelectorAll("[data-team]")
    .forEach((b) => (b.onclick = () => switchTeam(Number(b.dataset.team))));
  $("#allocation").innerHTML = allocationMarkup(dataset, t);
  $("#roster-board").innerHTML = rosterMarkup(dataset, t, dataset.rounds[0]);
  $("#settings").innerHTML =
    `<div class="panel garage-config"><div class="garage-inputs"><label>Team name<input id="team-name" maxlength="32" value="${esc(t.name)}"/></label><label>Total budget ($m)<input id="budget" type="number" min="0.1" step="0.1" value="${t.budget / 10}" aria-describedby="budget-help"/></label><label>Free transfers<select id="transfers"><option value="0" ${!t.initial && t.carry === 0 ? "selected" : ""}>2 free · established team</option><option value="1" ${!t.initial && t.carry === 1 ? "selected" : ""}>3 free · one carried</option><option value="initial" ${t.initial ? "selected" : ""}>Unlimited · new team</option></select></label></div><p class="sr-only" id="budget-help">Budget = team value + cash.</p>
   <fieldset class="chips"><legend>Chips</legend>${CHIPS.map((c) => {
     const supported = dataset.chip_support[c]?.available !== false;
     const available = t.chips.includes(c) && t.active !== c;
     return `<button type="button" class="chip-toggle chip-${c} ${available ? "available" : "used"}" data-chip="${c}" aria-pressed="${available}" aria-label="${chipNames[c]}: ${t.active === c ? "active" : available ? "available" : "used"}" ${!supported || t.active === c ? "disabled" : ""} title="${esc(supported ? chipDescriptions[c] : "History unavailable")}">${chipIcon(c)}<span>${chipNames[c]}</span></button>`;
   }).join("")}</fieldset>
  <div class="garage-utilities"><details class="advanced" id="active-setup" ${advancedOpen ? "open" : ""}><summary>Already activated a chip?</summary><label>Active this weekend<select id="active-chip"><option value="">None</option>${PREWEEK.map((c) => `<option value="${c}" ${t.active === c ? "selected" : ""}>${chipNames[c]}</option>`).join("")}</select></label>${
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
    <div class="import-export"><button id="export-team">Export team</button><label class="file-button">Import team<input type="file" id="import-team" accept="application/json,.json"/></label></div></div><p id="editor-error" class="error" role="alert" tabindex="-1">${esc(error)}</p></div>`;
  for (const id of ["budget", "transfers", "active-chip"])
    $(`#${id}`).onchange = () => {
      const value = $(`#${id}`);
      if (id === "budget") {
        try {
          parseMoney(value.value);
        } catch (e) {
          invalidate();
          clearTimeout(planningTimer);
          error = e.message;
          render();
          return;
        }
      }
      if (id === "budget") t.budget = parseMoney(value.value);
      else if (id === "transfers") {
        t.initial = value.value === "initial";
        t.carry = t.initial ? 0 : Number(value.value);
        t.completed = !t.initial;
      } else {
        t.active = value.value;
        t.chips = t.chips.filter((c) => c !== t.active);
      }
      invalidate();
      render();
    };
  if (t.weekendSuggestion) {
    const saved = t.weekendSuggestion;
    const ready = weekendReady(dataset, saved);
    $(".garage-utilities").insertAdjacentHTML(
      "afterend",
      `<section class="weekend-update" aria-label="After-weekend team update"><div><strong>Saved R${esc(saved.round)} · ${esc(saved.name)}</strong><p>${ready ? "Use only if you followed this suggestion. Cash is retained; team value uses the current prices. Check your official budget and transfers afterward." : "Available once this weekend has ended and the next round is published."}</p></div><button id="adopt-weekend" ${ready ? "" : "disabled"}>Update local team</button><button id="dismiss-weekend">Discard suggestion</button></section>`,
    );
    $("#adopt-weekend").onclick = () => {
      try {
        profiles[active] = adoptWeekend(dataset, team());
        invalidate();
        render();
      } catch (e) {
        error = e.message;
        render();
      }
    };
    $("#dismiss-weekend").onclick = () => {
      team().weekendSuggestion = null;
      save();
      render();
    };
  }
  $("#team-name").onchange = (e) => {
    t.name = e.target.value.trim() || `Team ${active + 1}`;
    save();
    render();
  };
  document.querySelectorAll("[data-remove]").forEach(
    (b) =>
      (b.onclick = () => {
        marketKind = dataset.assets.find((a) => a.id === b.dataset.remove).kind;
        $("#search").value = "";
        t.selected = t.selected.filter((id) => id !== b.dataset.remove);
        invalidate();
        render();
        location.hash = "asset-registry";
        route({ scroll: true });
        $("#search").focus({ preventScroll: true });
      }),
  );
  document.querySelectorAll("[data-chip]").forEach(
    (c) =>
      (c.onclick = () => {
        t.chips = t.chips.includes(c.dataset.chip)
          ? t.chips.filter((id) => id !== c.dataset.chip)
          : [...t.chips, c.dataset.chip];
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
  $("#export-team").onclick = exportTeam;
  $("#import-team").onchange = importTeam;
  renderStrategy();
  renderMarket();
  renderInsights();
  route();
  if (focused && document.getElementById(focused))
    document.getElementById(focused).focus({ preventScroll: true });
  else if (focusedChip)
    $(`[data-chip="${focusedChip}"]`)?.focus({ preventScroll: true });
}
function renderMarket() {
  if (!dataset) return;
  document
    .querySelectorAll("[data-kind]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(marketKind === b.dataset.kind)),
    );
  const query = $("#search").value.toLowerCase();
  const score = (asset) => total(dataset.rounds[0].forecasts[asset.id]);
  const comparators = {
    "price-desc": (a, b) => b.price_tenths_m - a.price_tenths_m,
    "price-asc": (a, b) => a.price_tenths_m - b.price_tenths_m,
    points: (a, b) => score(b) - score(a),
    value: (a, b) => score(b) / b.price_tenths_m - score(a) / a.price_tenths_m,
    name: (a, b) => a.name.localeCompare(b.name),
  };
  const available = dataset.assets
    .filter(
      (a) =>
        (marketKind === "ALL" || a.kind === marketKind) &&
        `${a.name} ${constructorName(dataset, a)}`
          .toLowerCase()
          .includes(query),
    )
    .sort(
      (a, b) => comparators[marketSort](a, b) || a.name.localeCompare(b.name),
    );
  $("#market-list").innerHTML =
    available.map((a) => registryCardMarkup(dataset, team(), a)).join("") ||
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
    error,
  );
  document.querySelectorAll("[data-round]").forEach(
    (b) =>
      (b.onclick = () => {
        selectedRound = Number(b.dataset.round);
        renderStrategy();
        $(`[data-round="${selectedRound}"]`).focus({ preventScroll: true });
      }),
  );
}
function renderInsights() {
  const focused = document.activeElement?.id;
  $("#insights").innerHTML = insightsMarkup(dataset, insightState);
  for (const key of ["round", "metric"]) {
    const control = $(`#insight-${key}`);
    if (control)
      control.onchange = () => {
        insightState[key] = control.value;
        renderInsights();
      };
  }
  document.querySelectorAll("[data-insight-population]").forEach(
    (b) =>
      (b.onclick = () => {
        insightState.population = b.dataset.insightPopulation;
        renderInsights();
        $(`[data-insight-population="${insightState.population}"]`).focus({
          preventScroll: true,
        });
      }),
  );
  document.querySelectorAll("[data-insight-entity]").forEach((button) => {
    button.onclick = () => {
      insightState.entity = button.dataset.insightEntity;
      renderInsights();
      if (window.matchMedia("(max-width: 760px)").matches)
        document
          .querySelector(".participant-prediction")
          ?.scrollIntoView({ block: "start" });
    };
  });
  const search = $("#insight-participant-search");
  const filterParticipants = () => {
    const rows = document.querySelectorAll("[data-participant-search]");
    rows.forEach(
      (r) =>
        (r.hidden = !r.dataset.participantSearch.includes(
          (insightState.participantQuery || "").trim().toLowerCase(),
        )),
    );
    if ($("#insight-participant-empty"))
      $("#insight-participant-empty").hidden = Array.from(rows).some(
        (r) => !r.hidden,
      );
  };
  if (search)
    search.oninput = () => {
      insightState.participantQuery = search.value;
      filterParticipants();
    };
  filterParticipants();
  if (focused && focused.startsWith("insight-"))
    document.getElementById(focused)?.focus({ preventScroll: true });
}
function acceptDataset(fresh) {
  dataset = fresh;
  for (const t of profiles) {
    if (t.season !== null && t.season !== dataset.season) {
      t.selected = [];
      t.chips = [...CHIPS];
      t.active = "";
      t.restore = [];
      t.weekendSuggestion = null;
    }
    t.season = dataset.season;
    t.allowPenalties = true;
    t.chips = t.chips.filter(
      (c) => dataset.chip_support[c]?.available !== false,
    );
  }
  save();
}
async function load() {
  if (busy) return;
  const request = revision;
  try {
    const fresh = await fetchDataset();
    if (request !== revision) return;
    if (JSON.stringify(fresh) === JSON.stringify(dataset)) {
      if (!result) queuePlan();
      return;
    }
    invalidate();
    acceptDataset(fresh);
    verificationText = "Price snapshot";
    queuePlan();
  } catch (e) {
    if (request !== revision) return;
    invalidate();
    clearTimeout(planningTimer);
    dataset = null;
    error = e.message;
    $("#publication-status").textContent = error;
  }
  render();
}
async function plan({ fill = false } = {}) {
  if (busy || !dataset || (!fill && team().selected.length !== 7)) return;
  try {
    if (fill) suggestionRequest(dataset, team());
    else validateTeam(dataset, team());
  } catch (e) {
    error = e.message;
    render();
    return;
  }
  busy = true;
  error = "";
  result = null;
  selectedRound = 0;
  render();
  const profile = active,
    request = revision;
  try {
    const fresh = await fetchDataset();
    if (!busy || profile !== active || request !== revision) return;
    if (JSON.stringify(fresh) !== JSON.stringify(dataset)) {
      acceptDataset(fresh);
      if (!fill) validateTeam(fresh, team());
    }
    const check = await verifyLive(fresh);
    if (!busy || profile !== active || request !== revision) return;
    verificationText = check.verified
      ? "Live prices verified"
      : "Price snapshot";
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
      try {
        validateDataset(dataset);
        if (fill && result) {
          const incomplete = team().selected.length !== 7;
          team().selected = result.rounds[0].entries.map((entry) => entry.id);
          if (incomplete) {
            team().initial = team().active !== "limitless";
            team().completed = false;
            team().carry = 0;
          }
          team().weekendSuggestion = null;
          result = null;
          save();
          render();
          queuePlan();
          return;
        }
        if (result) {
          team().weekendSuggestion = rememberWeekend(dataset, team(), result);
          save();
        }
      } catch (e) {
        result = null;
        error = e.message;
      }
      render();
    };
    worker.onerror = () => {
      if (request !== revision) return;
      worker?.terminate();
      worker = null;
      busy = false;
      error =
        "The browser solver failed to load. Refresh or try a WebAssembly-capable browser.";
      render();
    };
    worker.postMessage(
      fill
        ? suggestionRequest(fresh, team())
        : { dataset: fresh, team: structuredClone(team()) },
    );
  } catch (e) {
    if (request !== revision) return;
    busy = false;
    error = e.message;
    render();
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
      allowPenalties: true,
    };
    validateTeam(dataset, imported);
    invalidate();
    profiles[active] = imported;
    save();
    render();
    queuePlan();
  } catch (e) {
    error = `Cannot import team: ${e.message}`;
    render();
  }
}
shell();
render();
load();
setInterval(() => {
  if (!document.hidden) load();
}, 60_000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) load();
});
