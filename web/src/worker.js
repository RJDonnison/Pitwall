import loadHighs from "highs";
import wasmUrl from "highs/runtime?url";
import { optimize, validateDataset } from "./optimizer.js";

self.onmessage = async ({ data: { dataset, team } }) => {
  try {
    validateDataset(dataset);
    const highs = await loadHighs({ locateFile: () => wasmUrl });
    self.postMessage({ result: optimize(highs, dataset, team) });
  } catch (error) {
    self.postMessage({
      error: error.message || "The optimizer could not complete this plan.",
    });
  }
};
