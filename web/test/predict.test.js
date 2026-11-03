import test from "node:test";
import assert from "node:assert/strict";
import {
  predictMarkup,
  predictState,
  riskPreference,
  riskControlMarkup,
} from "../src/predict.js";

const now = Date.parse("2026-11-03T12:00:00Z");
test("risk control uses simple labels, defaults safely and renders the chosen recommendation", () => {
  assert.equal(riskPreference(null), "medium");
  assert.equal(riskPreference("unknown"), "medium");
  assert.equal(riskPreference("high"), "high");
  const control = riskControlMarkup("low");
  assert.match(control, /aria-label="Predict risk level"/);
  assert.match(control, /value="low" selected>Low<\/option>/);
  assert.match(control, />Medium<\/option>/);
  assert.match(control, />High<\/option>/);
  assert.doesNotMatch(control, /0\.5|0\.25|0\.1/);
  const publication = fixture();
  assert.match(
    predictMarkup(publication, now, "medium"),
    /awaiting a refreshed publication/,
  );
  assert.doesNotMatch(
    predictMarkup(publication, now, "medium"),
    /predict-picks/,
  );
  const low = structuredClone(publication.recommendation);
  low.answers[0].selected_options = ["c", "b", "a"];
  low.answers[0].standard_deviation = 20;
  low.answers[0].risk_score = 140;
  publication.recommendation.risk_profiles = { low };
  const html = predictMarkup(publication, now, "low");
  assert.match(html, /P1<\/span><strong>C/);
  assert.doesNotMatch(html, /predict-risk-note|Each question:|Boost follows|λ/);
  assert.doesNotMatch(html, /Score 140\.0|SD 20\.0|predict-risk-metrics/);
  assert.match(html, /Total expected points/);
});
function fixture() {
  const q = {
    id: 1,
    number: 1,
    template: 1,
    text: "Predict <the> podium",
    options: [
      { id: "a", name: "A <driver>", points: 10 },
      { id: "b", name: "B", points: 20 },
      { id: "c", name: "C", points: 30 },
    ],
  };
  return {
    schema_version: 1,
    status: "ready",
    season: 2026,
    gameday_id: 20,
    fetched_at: "2026-11-03T11:00:00Z",
    first_session_utc: "2026-11-06T12:00:00Z",
    locked: false,
    questions: [q],
    simulations: 4000,
    seed: 2026,
    telemetry: true,
    recommendation: {
      complete: true,
      expected_total_points: 150,
      unsupported: [],
      answers: [
        {
          question_id: 1,
          selected_options: ["a", "b", "c"],
          booster_id: "1",
          expected_points: 150,
          expected_points_before_boost: 75,
          probabilities: {
            a: [0.5, 0.2, 0.1],
            b: [0.2, 0.5, 0.1],
            c: [0.1, 0.1, 0.5],
          },
          model_type: "podium",
          calibration: {
            method: "uncalibrated_insufficient_prelock_archives",
            training_outcomes: 0,
            cutoff_utc: "2026-11-03T11:00:00Z",
          },
        },
      ],
    },
  };
}

test("risk profiles retain expected totals without displaying scores, calibration or summary Boost notes", () => {
  const publication = fixture();
  const values = { low: [100, 85], medium: [120, 100], high: [150, 140] };
  publication.recommendation.risk_profiles = {};
  for (const [name, [ev, score]] of Object.entries(values)) {
    const profile = structuredClone(publication.recommendation);
    profile.expected_total_points = ev;
    profile.answers[0].expected_points = ev;
    profile.answers[0].risk_score = score;
    publication.recommendation.risk_profiles[name] = profile;
    const html = predictMarkup(publication, now, name);
    const summary = html.match(
      /<section class="predict-summary[\s\S]*?<\/section>/,
    )[0];
    assert.match(
      summary,
      new RegExp(`predict-total">${ev.toFixed(1)} <small>pts`),
    );
    assert.doesNotMatch(
      html,
      /risk-adjusted score|risk-adjusted subtotal|predict-adjusted|predict-risk-metrics|Sum of question scores|Uncalibrated probabilities|Risk-level accuracy|predict-calibration/,
    );
    assert.doesNotMatch(summary, /2× Boost on question|No supported Boost/);
    assert.doesNotMatch(summary, /%|λ|NaN|undefined/);
  }
});

test("Predict preserves podium order and separates exact, any-podium, payout and Boost values", () => {
  const html = predictMarkup(fixture(), now);
  assert.match(html, /P1<\/span><strong>A &lt;driver&gt;/);
  assert.match(html, /50\.0% exact position · 80\.0% any podium/);
  assert.match(html, /26\.0 expected pts · 2× included/);
  assert.match(html, /52\.0 expected pts · 2× included/);
  assert.match(html, /72\.0 expected pts · 2× included/);
  assert.match(html, /150\.0 <small>pts/);
  assert.match(
    html,
    /P1 13\.0<\/span><span class="predict-slot-value">P2 10\.0/,
  );
  assert.equal((html.match(/<details /g) || []).length, 1);
  assert.match(html, /<summary>Payout breakdown/);
  assert.doesNotMatch(
    html,
    /<caption>|Full payout|half payout|Probabilities &/,
  );
  assert.doesNotMatch(html, /<driver>|<the>|NaN|undefined/);
});

test("podium driver expected points exclude Boost when it is assigned elsewhere", () => {
  const publication = fixture();
  Object.assign(publication.recommendation.answers[0], {
    booster_id: "0",
    expected_points: 75,
  });
  const html = predictMarkup(publication, now);
  assert.match(html, /13\.0 expected pts<\/span>/);
  assert.match(html, /26\.0 expected pts<\/span>/);
  assert.match(html, /36\.0 expected pts<\/span>/);
  assert.doesNotMatch(html, /2× included/);
});

test("Predict blocks stale, future-dated, locked and elapsed publications", () => {
  for (const overrides of [
    { fetched_at: "2026-11-03T06:00:00Z" },
    { fetched_at: "2026-11-04T00:00:00Z" },
    { locked: true },
    { status: "locked" },
    { first_session_utc: "2026-11-03T12:00:00Z" },
    { first_session_utc: "invalid" },
    { deadline_utc: "2026-11-03T11:59:00Z" },
  ]) {
    const publication = { ...fixture(), ...overrides };
    assert.equal(predictState(publication, now).available, false);
    assert.doesNotMatch(
      predictMarkup(publication, now),
      /Your recommended answer sheet|predict-picks/,
    );
  }
});

test("partial predictions keep unsupported reasons visible and label the subtotal", () => {
  const publication = fixture();
  publication.questions.push({
    id: 2,
    number: 2,
    text: "Unsupported <question>",
  });
  publication.recommendation.complete = false;
  publication.recommendation.unsupported.push({
    question_id: 2,
    reason: "Missing Sprint evidence",
  });
  const html = predictMarkup(publication, now);
  assert.match(html, /Partial answer sheet/);
  assert.match(html, /Supported answers expected points/);
  assert.match(html, /Missing Sprint evidence/);
  assert.match(html, /1 of 2 questions supported/);
});

test("a single answer exposes probability-times-payout rather than podium scoring", () => {
  const publication = fixture();
  publication.questions[0].template = 3;
  Object.assign(publication.recommendation.answers[0], {
    selected_options: ["b"],
    probabilities: { a: 0.6, b: 0.3, c: 0.1 },
  });
  const html = predictMarkup(publication, now);
  assert.match(html, /30\.0% model probability/);
  assert.doesNotMatch(html, /<caption>|Payout × model probability/);
  assert.match(html, /<td>10\.0<\/td><td>60\.0%<\/td><td>6\.0<\/td>/);
  assert.match(html, /<td>20\.0<\/td><td>30\.0%<\/td><td>6\.0<\/td>/);
  assert.match(html, /<td>30\.0<\/td><td>10\.0%<\/td><td>3\.0<\/td>/);
  assert.doesNotMatch(html, /exact position|any podium/);
  assert.doesNotMatch(html, /Recommended answer|Model evidence/);
});

test("Predict omits removed headings and raw feed failure details", () => {
  const ready = predictMarkup(fixture(), now);
  const unavailable = predictMarkup(
    {
      status: "unavailable",
      message:
        "Cannot verify fresh official Predict feed: questions/questions_20_en.json",
    },
    now,
  );
  assert.doesNotMatch(
    ready + unavailable,
    /F1 Predict · expected-points desk|One points-maximizing answer sheet|Cannot verify fresh official Predict feed|questions_20_en\.json|Published snapshot|Exact lock deadline unavailable|Lock state at publication|Boost extra|Highest expected gain|Recommended answer|Model evidence|Behind the answer sheet|Probability meets payout/,
  );
  assert.match(unavailable, /temporarily unavailable/);
});
