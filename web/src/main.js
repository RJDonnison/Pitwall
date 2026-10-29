import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "./style.css";
import { CHIPS, PREWEEK, total, validateTeam } from "./optimizer.js";
import { fetchDataset, verifyLive } from "./data.js";

const chipNames = {
  autopilot: "Autopilot",
  x3: "3× Boost",
  no_negative: "No Negative",
  wildcard: "Wildcard",
  limitless: "Limitless",
  final_fix: "Final Fix",
};
const chipDescriptions = {
  autopilot: "2× goes to the best selected driver across the whole weekend.",
  x3: "Triple one driver, with a different driver on regular 2×.",
  no_negative:
    "Removes negative scoring categories; transfer penalties still apply.",
  wildcard: "Unlimited transfers within your budget.",
  limitless: "Unlimited budget and transfers, then your original team returns.",
  final_fix:
    "One future-only swap after qualifying. Reassess in the official window; not spent by this pre-weekend plan.",
};
const $ = (query) => document.querySelector(query);
const esc = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const points = (value) =>
  Number(value).toLocaleString(undefined, {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  });
const money = (value) => `$${(value / 10).toFixed(1)}m`;
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
const date = (value) =>
  new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
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
  marketKind = "DRIVER",
  worker = null,
  error = "",
  busy = false,
  verification = "";
let previewAllowed = false;
let revision = 0;
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
  if (worker) worker.terminate();
  worker = null;
  busy = false;
  result = null;
  error = "";
  save();
}

function shell() {
  $("#app").innerHTML = `
    <header class="masthead"><a class="brand" href="./"><svg viewBox="0 0 36 32" aria-hidden="true"><path d="M2 5h29l-5 7H10l-3 5h15l-5 7H2l7-12H2z" fill="currentColor"/></svg><span>Pitwall</span></a><span class="header-title">Your season, planned.</span><a href="#how-it-works">How it works</a></header>
    <main><section class="intro"><div><h1>A better team.<br>A longer view.</h1><p>Set your seven. Plan every remaining round, with chips and transfers working together.</p></div><div class="race-stamp" id="race-stamp">Loading the season…</div></section>
    <div id="data-state" class="data-state" role="status">Fetching the latest published forecasts…</div>
    <div class="workspace"><aside class="editor" aria-label="Your team editor"><div class="team-tabs" role="group" aria-label="Saved teams">${profiles.map((t, i) => `<button data-team="${i}" aria-pressed="${i === active}">${esc(t.name)}</button>`).join("")}</div><div id="settings"></div></aside>
    <section class="strategy" aria-label="Season strategy"><div id="strategy"></div><section class="market"><div class="section-heading"><div><h2>The grid</h2><p>Every selection’s forecast. Prices are in millions.</p></div><label class="round-select">Points for<select id="market-round" aria-label="Round for grid forecasts"></select></label></div><div class="market-tools"><div role="group" aria-label="Asset type"><button id="drivers-tab" aria-pressed="true">Drivers</button><button id="constructors-tab" aria-pressed="false">Constructors</button></div><input id="search" type="search" aria-label="Search drivers and constructors" placeholder="Find a driver or constructor" /></div><div id="market-list"></div></section></section></div>
    <section id="how-it-works" class="method"><h2>Think in seasons. Check before you change.</h2><div><p><strong>One joint plan.</strong> An exact mixed-integer optimizer runs on your device. It considers five drivers, two constructors, 2× Boost, once-per-season chips, Sprint weekends, net transfers and their penalties across all published remaining rounds.</p><p><strong>Forecasts, not promises.</strong> Historical inputs precede the predicted weekend. Future prices stay at today’s snapshot values. Re-plan as prices, results and your team change. Final Fix needs a separate post-qualifying decision; it is not assigned a speculative pre-weekend value.</p><p><strong>Your teams stay here.</strong> Three team profiles are stored in this browser. There is no account sign-in, server-side team storage or automatic submission. A published snapshot is a preview; check the official game’s prices, eligibility and lock before making changes.</p></div><a href="https://fantasy.formula1.com/en/game-rules" target="_blank" rel="noopener noreferrer">Official Fantasy rules</a></section></main><footer><span>Pitwall · Independent F1 Fantasy planning</span><span>Not affiliated with Formula 1.</span></footer>`;
  document.querySelectorAll("[data-team]").forEach(
    (b) =>
      (b.onclick = () => {
        invalidate();
        active = Number(b.dataset.team);
        verification = "";
        shell();
        render();
      }),
  );
  $("#market-round").onchange = (e) => {
    marketRound = Number(e.target.value);
    renderMarket();
  };
  $("#search").oninput = renderMarket;
  $("#drivers-tab").onclick = () => {
    marketKind = "DRIVER";
    renderMarket();
  };
  $("#constructors-tab").onclick = () => {
    marketKind = "CONSTRUCTOR";
    renderMarket();
  };
}

function render() {
  if (!dataset) {
    $("#market-list").innerHTML = "";
    $("#market-round").innerHTML = "";
    $("#settings").innerHTML =
      '<p class="empty">Your team editor will appear when verified forecast inputs are published.</p>';
    $("#strategy").innerHTML =
      `<div class="empty-state"><h2>Waiting for the grid</h2><p>${esc(error || "Loading public roster and forecasts…")}</p><button id="reload">Refresh data</button></div>`;
    $("#reload").onclick = load;
    return;
  }
  $("#race-stamp").innerHTML =
    `<strong>${dataset.season}</strong><span>${dataset.rounds.length} rounds remaining</span><small>Next: ${esc(dataset.rounds[0].name.replace(" Grand Prix", ""))}</small>`;
  $("#data-state").innerHTML =
    `<span class="data-dot"></span><div><strong>Planning preview</strong> · Prices checked ${esc(new Date(dataset.price_checked_at).toLocaleString())}<br><small>${esc(verification || "Live prices are not verified in this static site. Published data expires after six hours.")}</small></div><button id="refresh">Refresh data</button>`;
  $("#refresh").onclick = () => {
    invalidate();
    load();
  };
  document.querySelectorAll("[data-team]").forEach((b, i) => {
    b.textContent = profiles[i].name;
    b.setAttribute("aria-pressed", String(i === active));
  });
  const t = team(),
    chosen = dataset.assets.filter((a) => t.selected.includes(a.id));
  const count = (kind) => chosen.filter((a) => a.kind === kind).length;
  $("#settings").innerHTML =
    `<div class="editor-body"><div class="section-heading"><h2>Your starting team</h2><span class="selection-count">${count("DRIVER")}/5 drivers · ${count("CONSTRUCTOR")}/2 constructors</span></div>
    <label>Team name<input id="team-name" maxlength="32" value="${esc(t.name)}" /></label>
    <div class="starting-roster">${["DRIVER", "CONSTRUCTOR"]
      .map(
        (kind) =>
          `<div class="roster-group">${Array.from(
            { length: kind === "DRIVER" ? 5 : 2 },
            (_, i) => {
              const a = chosen.filter((a) => a.kind === kind)[i];
              return a
                ? `<button class="roster-pick" data-remove="${esc(a.id)}" title="Remove ${esc(a.name)}"><span>${esc(a.tla || a.name)}</span><small>${money(a.price_tenths_m)}</small><span aria-hidden="true">×</span></button>`
                : `<span class="roster-slot">Choose ${kind === "DRIVER" ? "driver" : "constructor"} ${i + 1} from the grid</span>`;
            },
          ).join("")}</div>`,
      )
      .join("")}</div>
    <div class="form-grid"><label>Total budget ($m)<input id="budget" type="number" min="0.1" step="0.1" value="${t.budget / 10}" aria-describedby="budget-help" /></label><label>Carried transfer<select id="carry"><option value="0" ${t.carry === 0 ? "selected" : ""}>0 carried (2 free)</option><option value="1" ${t.carry === 1 ? "selected" : ""}>1 carried (3 free)</option></select></label></div>
    <p class="hint" id="budget-help">Total team value + cash, not just cash. Selected cost: <strong>${money(total(chosen.map((a) => a.price_tenths_m)))}</strong>. Use your original race-week roster to count net transfers.</p>
    <label class="check"><input type="checkbox" id="initial" ${t.initial ? "checked" : ""}/> My team has not scored a race yet</label>
    <label class="check"><input type="checkbox" id="completed" ${t.completed ? "checked" : ""}/> I have completed a full race weekend</label>
    <label class="check"><input type="checkbox" id="penalties" ${t.allowPenalties ? "checked" : ""}/> Allow paid transfers when worth the −10 points each</label>
    <fieldset class="chips"><legend>Chips still available</legend>${CHIPS.map(
      (c) => {
        const supported = dataset.chip_support[c]?.available !== false;
        return `<label class="chip-option" title="${esc(chipDescriptions[c])}"><input type="checkbox" data-chip="${c}" ${t.chips.includes(c) ? "checked" : ""} ${!supported ? "disabled" : ""}/><span>${chipNames[c]}</span><small>${supported ? (c === "final_fix" ? "After qualifying" : "Once this season") : "History unavailable"}</small></label>`;
      },
    ).join("")}</fieldset>
    <details class="advanced"><summary>Already activated a chip?</summary><label>Active this weekend<select id="active-chip"><option value="">None</option>${PREWEEK.map((c) => `<option value="${c}" ${t.active === c ? "selected" : ""}>${chipNames[c]}</option>`).join("")}</select></label>${
      t.active === "limitless"
        ? `<label>Team restored after Limitless<select id="restore" multiple size="7">${[
            "DRIVER",
            "CONSTRUCTOR",
          ]
            .map(
              (k) =>
                `<optgroup label="${k === "DRIVER" ? "Choose five drivers" : "Choose two constructors"}">${dataset.assets
                  .filter((a) => a.kind === k)
                  .map(
                    (a) =>
                      `<option value="${a.id}" ${t.restore.includes(a.id) ? "selected" : ""}>${esc(a.name)}</option>`,
                  )
                  .join("")}</optgroup>`,
            )
            .join(
              "",
            )}</select></label><p class="hint">Select the original seven using Ctrl/Cmd. This restoration roster is required for a full-season plan.</p>`
        : '<p class="hint">Active chips keep their effect even after being removed from your remaining inventory. Final Fix requires remaining-session planning outside this preview.</p>'
    }</details>
    <div class="import-export"><button id="export-team" class="quiet">Export team</button><label class="file-button">Import team<input type="file" id="import-team" accept="application/json,.json" /></label></div>
    <label class="check preview-consent"><input type="checkbox" id="preview-consent" ${previewAllowed ? "checked" : ""}/> Allow a published-snapshot preview if live prices cannot be verified</label>
    <button id="optimize" class="primary" ${busy ? "disabled" : ""}>${busy ? "Planning the season…" : "Plan the rest of my season"}</button>${busy ? '<button id="cancel" class="quiet">Cancel planning</button>' : ""}<p id="editor-error" class="error" role="alert" tabindex="-1">${esc(error)}</p><p class="hint">Changing inputs clears the plan. No website changes are submitted.</p></div>`;
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
        id === "budget"
          ? parseMoney(value.value)
          : id === "carry"
            ? Number(value.value)
            : id === "active-chip"
              ? value.value
              : value.checked;
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
}

function renderMarket() {
  if (!dataset) return;
  $("#drivers-tab").setAttribute(
    "aria-pressed",
    String(marketKind === "DRIVER"),
  );
  $("#constructors-tab").setAttribute(
    "aria-pressed",
    String(marketKind === "CONSTRUCTOR"),
  );
  const query = $("#search").value.toLowerCase(),
    r = dataset.rounds[marketRound];
  const available = dataset.assets
    .filter(
      (a) => a.kind === marketKind && a.name.toLowerCase().includes(query),
    )
    .sort((a, b) => total(r.forecasts[b.id]) - total(r.forecasts[a.id]));
  $("#market-list").innerHTML =
    `<div class="market-labels"><span>Selection / price</span><span>Predicted points</span><span></span></div>${available
      .map((a) => {
        const selected = team().selected.includes(a.id);
        const count = team().selected.filter(
          (id) => asset(id)?.kind === a.kind,
        ).length;
        return `<div class="asset-row ${selected ? "selected" : ""}"><div><strong>${esc(a.name)}</strong><small>${esc(a.kind === "DRIVER" ? dataset.assets.find((c) => c.kind === "CONSTRUCTOR" && c.team_id === a.team_id)?.name || "" : "Constructor")} <span>${money(a.price_tenths_m)}</span></small></div><div class="asset-points"><strong>${points(total(r.forecasts[a.id]))}</strong><small>Q ${points(r.forecasts[a.id][0])} ${r.sprint ? `· S ${points(r.forecasts[a.id][1])}` : ""} · R ${points(r.forecasts[a.id][2])}</small></div><button data-select="${a.id}" aria-label="${selected ? "Remove" : "Add"} ${esc(a.name)}" aria-pressed="${selected}" ${!selected && count >= (a.kind === "DRIVER" ? 5 : 2) ? "disabled" : ""}>${selected ? "✓" : "+"}</button></div>`;
      })
      .join(
        "",
      )}${available.length === 0 ? '<p class="empty">No matching selections. Try another name.</p>' : ""}`;
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
  if (!result) {
    $("#strategy").innerHTML =
      `<div class="empty-state"><div class="track-mark" aria-hidden="true"><svg viewBox="0 0 260 125"><path d="M20 85L55 30 125 20 150 50 225 40 240 65 185 100 110 105 85 75 45 100Z"/></svg></div><h2>${busy ? "Working through the possibilities" : "Build your season strategy"}</h2><p>${busy ? "Choosing lineups, transfer timing and chips together. Your browser stays responsive; a full season can take up to 90 seconds." : "Choose five drivers and two constructors, enter your available budget and chips, then plan all remaining rounds."}</p><div class="empty-key"><span>5 drivers + 2 constructors</span><span>Whole-season chip timing</span><span>Runs on your device</span></div></div>`;
    return;
  }
  const baseline = total(
    dataset.rounds.map((r) => {
      const scores = team().selected.map((id) => total(r.forecasts[id]));
      return (
        total(scores) +
        Math.max(
          ...team()
            .selected.filter((id) => asset(id).kind === "DRIVER")
            .map((id) => total(r.forecasts[id])),
        )
      );
    }),
  );
  $("#strategy").innerHTML =
    `<div class="plan-summary"><div><span>${esc(team().name)} · ${dataset.season} season preview</span><h2>${points(result.points)} <small>predicted points</small></h2><p>${points(result.points - baseline)} vs keeping this roster with 2× only. Includes transfer penalties.</p></div><span class="solver-badge">Proven optimal<br><small>for these forecast inputs</small></span></div><div class="round-strip" aria-label="Season chip calendar">${result.rounds.map((r, i) => `<button data-round="${i}"><small>R${r.round} · ${date(r.first_session_utc)}${r.sprint ? " · Sprint" : ""}</small><strong>${esc(r.name.replace(" Grand Prix", ""))}</strong><span>${r.chip ? chipNames[r.chip] : "Save chips"}</span><b>${points(r.points)} <small>pts</small></b></button>`).join("")}</div><div class="plan-rounds">${result.rounds.map((r, i) => `<details class="round-detail" ${i === 0 ? "open" : ""} id="round-${i}"><summary><span class="round-number">R${r.round}</span><span class="round-name"><strong>${esc(r.name)}</strong><small>${r.sprint ? "Sprint weekend" : "Regular weekend"} · ${r.chip ? chipNames[r.chip] : "No chip"} · ${r.transfers} net transfers</small></span><strong class="round-total">${points(r.points)}<small>pts</small></strong></summary><div class="round-body"><div class="transfer-summary"><div><span>Bring in</span><strong>${r.in.map((id) => esc(asset(id).name)).join(", ") || "Keep all seven"}</strong></div><div><span>Move out</span><strong>${r.out.map((id) => esc(asset(id).name)).join(", ") || "No outgoing selections"}</strong></div></div><p class="chip-note">${r.chip ? esc(chipDescriptions[r.chip]) : "Keep unused chips for a more valuable round."} ${r.chip === "limitless" ? "The durable roster is restored for the following round." : ""}</p><div class="table-scroll"><table><caption>Predicted points including Boost and chip effects</caption><thead><tr><th>Selection</th><th>Q</th>${r.sprint ? "<th>Sprint</th>" : ""}<th>Race</th><th>Total</th></tr></thead><tbody>${r.entries.map((e) => `<tr><th>${esc(asset(e.id).name)} ${e.id === r.boost && r.chip !== "autopilot" ? '<span class="boost-tag">2×</span>' : ""}${e.id === r.x3 ? '<span class="boost-tag triple">3×</span>' : ""}</th><td>${points(e.sessions[0])}</td>${r.sprint ? `<td>${points(e.sessions[1])}</td>` : ""}<td>${points(e.sessions[2])}</td><td><strong>${points(e.points)}</strong></td></tr>`).join("")}</tbody></table></div><div class="round-footer"><span>Lineup ${money(r.cost)} ${r.chip === "limitless" ? "(uncapped)" : `/ ${money(team().budget)}`}</span><span>Penalty −${r.penalty} pts</span><span>${i < result.rounds.length - 1 ? `${r.carry} carried forward` : "Season horizon ends"}</span></div></div></details>`).join("")}</div><p class="plan-disclaimer">Planning preview from published data. Future prices held constant. Re-plan before every race; verify live eligibility and prices on the official game. Final Fix remains a separate post-qualifying decision.</p>`;
  document.querySelectorAll("[data-round]").forEach(
    (b) =>
      (b.onclick = () => {
        const i = Number(b.dataset.round);
        $(`#round-${i}`).open = true;
        $(`#round-${i}`).scrollIntoView({
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
          block: "nearest",
        });
        marketRound = i;
        $("#market-round").value = String(i);
        renderMarket();
      }),
  );
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
    $("#editor-error").focus();
    return;
  }
  busy = true;
  error = "";
  result = null;
  render();
  const profile = active;
  const request = ++revision;
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
    worker.postMessage({ dataset: fresh, team: structuredClone(team()) });
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
