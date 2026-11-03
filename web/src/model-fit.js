const signed = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}`;

// Forecast accuracy for the footer: the current score and its change since last weekend.
export function accuracyText(dataset) {
  const part = dataset?.model?.fit?.pre_weekend;
  if (!part || !Number.isFinite(part.accuracy)) return "";
  const change = Number.isFinite(part.previous_accuracy)
    ? Math.round((part.accuracy - part.previous_accuracy) * 10) / 10
    : null;
  return `Forecast accuracy ${part.accuracy.toFixed(1)}%${change === null ? "" : change === 0 ? " (no change)" : ` (${signed(change)})`}`;
}
