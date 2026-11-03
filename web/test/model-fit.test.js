import test from "node:test";
import assert from "node:assert/strict";
import { accuracyText } from "../src/model-fit.js";

const fit = (accuracy, previous_accuracy) => ({
  model: { fit: { pre_weekend: { accuracy, previous_accuracy } } },
});

test("footer accuracy shows the score and its change since last weekend", () => {
  assert.equal(accuracyText(fit(86.6, 85.9)), "Forecast accuracy 86.6% (+0.7)");
  assert.equal(accuracyText(fit(85.9, 86.6)), "Forecast accuracy 85.9% (−0.7)");
  assert.equal(accuracyText(fit(86.6, 86.6)), "Forecast accuracy 86.6% (no change)");
  assert.equal(accuracyText(fit(86.6, null)), "Forecast accuracy 86.6%");
});

test("footer accuracy is empty without a fit", () => {
  assert.equal(accuracyText({ model: {} }), "");
  assert.equal(accuracyText(undefined), "");
});
