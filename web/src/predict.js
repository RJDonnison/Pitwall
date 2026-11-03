import { esc } from "./text.js";

const number = (n) => n.toFixed(1);
const percent = (n) => `${(n * 100).toFixed(1)}%`;
const stamp = (value) =>
  new Date(value).toLocaleString(undefined, {
    timeZone: "UTC",
    dateStyle: "medium",
    timeStyle: "short",
  }) + " UTC";

export function predictState(publication, now = Date.now()) {
  if (!publication || publication.status === "unavailable")
    return {
      available: false,
      message:
        publication?.message ||
        "Fetching official questions and model recommendations…",
    };
  const fetched = Date.parse(publication.fetched_at);
  if (
    !Number.isFinite(fetched) ||
    fetched > now ||
    now - fetched >= 6 * 60 * 60 * 1000
  )
    return {
      available: false,
      message:
        "This Predict snapshot has expired. Waiting for a fresh official question and payout check.",
    };
  if (
    publication.locked ||
    publication.status === "locked" ||
    now >= Date.parse(publication.first_session_utc)
  )
    return {
      available: false,
      message:
        publication.message ||
        "This round is locked or has started. Pre-weekend recommendations are closed.",
    };
  if (!Number.isFinite(Date.parse(publication.first_session_utc)))
    return {
      available: false,
      message: "The official event timing could not be verified.",
    };
  if (publication.deadline_utc && now >= Date.parse(publication.deadline_utc))
    return {
      available: false,
      message: "The published official deadline has passed.",
    };
  return { available: true };
}

function questionMarkup(q, answer, unsupported) {
  if (!answer)
    return `<article class="panel predict-question"><div class="section-heading"><span class="eyebrow">Question ${q.number}</span><span class="tag">Unsupported</span></div><div class="predict-question-body"><h2>${esc(q.text)}</h2><p class="insight-empty">${esc(unsupported?.reason || "No established model for this question.")}</p></div></article>`;
  const podium = q.template === 1;
  const boost = answer.booster_id === "1";
  const selections = new Map(answer.selected_options.map((id, i) => [id, i]));
  const options = q.options
    .map((o) => {
      const p = answer.probabilities[o.id];
      const ev = podium
        ? p.map((v) => o.points * (p.reduce((a, b) => a + b, 0) + v))
        : o.points * p;
      return { ...o, p, ev };
    })
    .sort((a, b) =>
      podium ? Math.max(...b.ev) - Math.max(...a.ev) : b.ev - a.ev,
    );
  return `<article class="panel predict-question ${boost ? "predict-boosted" : ""}">
    <div class="section-heading"><span class="eyebrow">Question ${q.number} · ${podium ? "Ordered podium" : "Single answer"}</span>${boost ? '<span class="tag red">2× question Boost</span>' : ""}</div>
    <div class="predict-question-body"><h2>${esc(q.text)}</h2>${q.subtext ? `<p>${esc(q.subtext)}</p>` : ""}
    <ol class="predict-picks ${podium ? "predict-podium" : ""}">${answer.selected_options
      .map((id, i) => {
        const o = options.find((o) => o.id === id);
        return `<li>${podium ? `<span class="predict-place">P${i + 1}</span>` : '<span class="eyebrow">Recommended answer</span>'}<strong>${esc(o.name)}</strong><small>${podium ? `${percent(o.p[i])} exact position · ${percent(o.p.reduce((a, b) => a + b, 0))} any podium` : `${percent(o.p)} model probability`}</small></li>`;
      })
      .join("")}</ol>
    <div class="predict-score"><span>Expected points${boost ? " · 2× included" : ""}</span><strong>${number(answer.expected_points)} <small>pts</small></strong></div>
    ${boost ? `<p class="predict-note">${number(answer.expected_points_before_boost)} base + ${number(answer.expected_points_before_boost)} Boost extra. Highest expected gain among supported questions.</p>` : ""}
    <details class="predict-options"><summary>Probabilities & payout breakdown · ${options.length} options</summary><div class="predict-table"><table><caption>${podium ? "Payout × (any-podium probability + exact-position probability), before Boost. Each driver can occupy only one slot." : "Payout × model probability, before Boost. Ranked by expected points."}</caption><thead><tr><th>Legal answer</th><th>Payout</th>${podium ? "<th>P1 / P2 / P3 probability</th><th>P1 / P2 / P3 expected pts</th>" : "<th>Probability</th><th>Expected pts</th>"}</tr></thead><tbody>${options.map((o) => `<tr class="${selections.has(o.id) ? "predict-selected" : ""}"><th scope="row">${esc(o.name)}${selections.has(o.id) ? `<small>${podium ? `Selected P${selections.get(o.id) + 1}` : "Selected"}</small>` : ""}</th><td>${number(o.points)}</td><td>${podium ? o.p.map(percent).join(" / ") : percent(o.p)}</td><td>${podium ? o.ev.map(number).join(" / ") : number(o.ev)}</td></tr>`).join("")}</tbody></table></div></details>
    <details class="predict-evidence"><summary>Model evidence</summary><p>${esc(answer.model_type)}</p><p>${answer.calibration.method === "uncalibrated_insufficient_prelock_archives" ? "Uncalibrated · insufficient earlier settled pre-lock archives" : "Chronological probability calibration"} · ${answer.calibration.training_outcomes} training outcomes.</p><p>Calibration cutoff: ${esc(stamp(answer.calibration.cutoff_utc))}</p></details></div></article>`;
}

export function predictMarkup(publication, now = Date.now()) {
  const state = predictState(publication, now);
  const heading = `<div class="page-heading predict-heading"><div><span class="eyebrow">F1 Predict · expected-points desk</span><h1>Make every answer count.</h1><p>Official questions. Model probabilities. One points-maximizing answer sheet.</p></div><a class="predict-official" href="https://f1predict.formula1.com/" target="_blank" rel="noopener noreferrer">Open F1 Predict ↗</a></div>`;
  if (!state.available)
    return `<div class="predict-page">${heading}<section class="panel predict-unavailable" role="status"><span class="eyebrow">${publication ? "Recommendations unavailable" : "Checking publication"}</span><h2>${publication?.locked || publication?.status === "locked" ? "Round closed" : "Awaiting verified inputs"}</h2><p>${esc(state.message)}</p>${publication?.fetched_at ? `<p>Last checked ${esc(stamp(publication.fetched_at))}</p>` : ""}</section></div>`;
  const result = publication.recommendation;
  if (!result)
    return `<div class="predict-page">${heading}<section class="panel predict-unavailable" role="status">No verified recommendation in this publication.</section></div>`;
  const boosted = result.answers.find((a) => a.booster_id === "1");
  return `<div class="predict-page">${heading}
    <section class="predict-summary panel" aria-label="Predict recommendation summary"><div><span class="eyebrow">${publication.season} · official round ${publication.gameday_id}</span><h2>${result.complete ? "Your recommended answer sheet" : "Partial answer sheet"}</h2><p>${result.answers.length} of ${publication.questions.length} questions supported${result.complete ? "" : " · unsupported questions need your own decision"}</p></div><div><span class="eyebrow">${result.complete ? "Total" : "Supported answers"} expected points</span><strong class="predict-total">${number(result.expected_total_points)} <small>pts</small></strong><p>${boosted ? `2× Boost on question ${publication.questions.find((q) => q.id === boosted.question_id).number}` : "No supported Boost"}</p></div></section>
    <div class="predict-publication"><p><span class="tag">Published snapshot</span> Checked ${esc(stamp(publication.fetched_at))} · refreshed every two hours.</p><p>${publication.deadline_utc && publication.deadline_authority ? `Official deadline: ${esc(stamp(publication.deadline_utc))}` : "Exact lock deadline unavailable. Check the official game; session start is not a verified deadline."} Lock state at publication: open.</p></div>
    <div class="predict-question-grid">${publication.questions
      .map((q) =>
        questionMarkup(
          q,
          result.answers.find((a) => a.question_id === q.id),
          result.unsupported.find((a) => a.question_id === q.id),
        ),
      )
      .join("")}</div>
    <section class="panel predict-method"><span class="eyebrow">Behind the answer sheet</span><h2>Probability meets payout.</h2><p>The highest expected-scoring answer can differ from the most likely outcome. Ordered podium slots are optimized together without repeating a driver. One question receives a 2× Boost.</p><p>${publication.simulations.toLocaleString()} simulations · seed ${publication.seed} · ${publication.telemetry ? "telemetry enabled" : "telemetry disabled"}. Forecasts use earlier results only. Probabilities are uncertain; a larger expected score is not a guaranteed result. Public website forecasts have no settled Predict calibration archive.</p><p>Predict payouts are separate from Fantasy points. These recommendations do not submit answers. Verify the latest options, payouts and lock state on the official game before making your picks.</p><a href="https://f1predict.formula1.com/en/game-rules" target="_blank" rel="noopener noreferrer">Official Predict scoring rules ↗</a></section></div>`;
}
