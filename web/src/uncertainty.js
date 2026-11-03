// Approximate 80% ranges built from the published per-session prediction ranges.
// Session and asset errors are combined as if independent (root-sum-of-squares),
// so these are indicative ranges, not guarantees.

const radius = (interval) =>
  interval && Number.isFinite(interval.low) && Number.isFinite(interval.high)
    ? (interval.high - interval.low) / 2
    : null;

// Half-width for one asset's weekend total, or null without a published range.
export function assetHalfWidth(round, assetId, multiplier = 1) {
  const sessions = Object.values(round?.intervals?.[assetId] || {});
  if (!sessions.length) return null;
  const radii = sessions.map(radius);
  if (radii.some((r) => r === null)) return null;
  return multiplier * Math.sqrt(radii.reduce((s, r) => s + r * r, 0));
}

// Half-width of a planned weekend (all selected assets, boosts counted by their
// multiplier), or null when any selected asset has no published range.
export function roundHalfWidth(planned) {
  const parts = planned.entries.map((e) => {
    const base = e.base.reduce((s, v) => s + v, 0);
    const multiplier = Math.abs(base) > 1e-9 ? Math.max(1, e.points / base) : 1;
    return assetHalfWidth(planned, e.id, multiplier);
  });
  if (!parts.length || parts.some((p) => p === null)) return null;
  return Math.sqrt(parts.reduce((s, p) => s + p * p, 0));
}

// Cumulative bands for the season plan: [{low, high}] aligned with plan rounds,
// or null from the first round that lacks a range onward.
export function planBands(rounds) {
  let variance = 0;
  let sum = 0;
  let broken = false;
  return rounds.map((r) => {
    sum += r.points;
    const half = broken ? null : roundHalfWidth(r);
    if (half === null) {
      broken = true;
      return null;
    }
    variance += half * half;
    const spread = Math.sqrt(variance);
    return { low: sum - spread, high: sum + spread };
  });
}
