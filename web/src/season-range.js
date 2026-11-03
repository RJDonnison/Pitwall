// Empirical weekend-block bootstrap: selections share one historical outcome
// per weekend; future weekends are drawn independently, not paired by index.
const sum = (values) => values.reduce((a, b) => a + b, 0);
const simulations = 2048;

export function scenarioPoints(round, scenario, driverIds) {
  const scores =
    round.chip === "no_negative" ? scenario.no_negative : scenario.scores;
  const values = round.entries.map(({ id }) => scores?.[id]);
  if (
    values.some(
      (v) =>
        !Array.isArray(v) ||
        v.length !== 3 ||
        v.some((n) => !Number.isFinite(n)),
    )
  )
    return null;
  const totals = Object.fromEntries(
    round.entries.map(({ id }, i) => [id, sum(values[i])]),
  );
  const boost =
    round.chip === "autopilot"
      ? Math.max(
          ...round.entries
            .filter(({ id }) => driverIds.has(id))
            .map(({ id }) => totals[id]),
        )
      : totals[round.boost];
  const score =
    sum(Object.values(totals)) +
    boost +
    (round.x3 ? 2 * totals[round.x3] : 0) -
    round.penalty;
  return Number.isFinite(score) ? score : null;
}

export function seasonRange(dataset, rounds) {
  const driverIds = new Set(
    dataset.assets.filter((a) => a.kind === "DRIVER").map((a) => a.id),
  );
  const paths = new Array(simulations).fill(0);
  const bands = [];
  let expected = 0;
  let seed = 2026;
  const random = () => {
    seed = (Math.imul(1664525, seed) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  for (const round of rounds) {
    const samples = round.joint_scenarios?.map((s) =>
      scenarioPoints(round, s, driverIds),
    );
    if (!samples || samples.length < 2 || samples.some((s) => s === null)) {
      return {
        status: "unavailable",
        message:
          "Prediction range unavailable: at least two complete same-format joint weekends are required for every planned round.",
      };
    }
    const mean = sum(samples) / samples.length;
    expected += round.points;
    // Centre joint team deviations on the optimizer's expected net score.
    // In particular, preserve its whole-weekend Autopilot expectation.
    for (let i = 0; i < simulations; i++)
      paths[i] +=
        round.points + samples[Math.floor(random() * samples.length)] - mean;
    const sorted = [...paths].sort((a, b) => a - b);
    const quantile = (p) => {
      const index = (sorted.length - 1) * p;
      const lower = Math.floor(index);
      return (
        sorted[lower] +
        (sorted[Math.ceil(index)] - sorted[lower]) * (index - lower)
      );
    };
    bands.push({
      low: quantile(0.1),
      high: quantile(0.9),
      expected,
      samples: samples.length,
    });
  }
  return {
    status: "ready",
    bands,
    simulations,
    message:
      "80% simulated range · provisional. Whole-weekend driver/constructor outcomes are sampled together; future weekends are assumed independent. Historical variation is centred on planned net points. Coverage is not calibrated.",
  };
}
