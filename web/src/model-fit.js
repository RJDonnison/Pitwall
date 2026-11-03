const pctText = (v) => (Number.isFinite(v) ? `${v.toFixed(1)}%` : "n/a");

const score = (label, value) =>
  `<div class="fit-family"><span class="fit-title">${label}</span><strong class="fit-accuracy">${pctText(value)}</strong></div>`;

export function modelFitMarkup(dataset) {
  const part = dataset?.model?.fit?.pre_weekend;
  if (!part) return "";
  return `<section class="panel model-fit" aria-label="Accuracy">
    <div class="section-heading"><h2>Accuracy</h2></div>
    <div class="fit-grid">${score("Before qualifying · this weekend", part.accuracy)}${score("Before qualifying · last weekend", part.previous_accuracy)}</div>
  </section>`;
}
