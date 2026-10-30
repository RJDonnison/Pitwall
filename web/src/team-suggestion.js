import { validateDataset, validateTeam } from "./optimizer.js";

// A seed only makes the existing solver's roster contract valid. Initial-team
// transfers are free, so every legal seven-selection lineup remains available.
export function suggestionRequest(dataset, team) {
  validateDataset(dataset);
  const selected = ["DRIVER", "CONSTRUCTOR"].flatMap((kind) =>
    dataset.assets
      .filter((a) => a.kind === kind)
      .sort(
        (a, b) =>
          a.price_tenths_m - b.price_tenths_m || a.id.localeCompare(b.id),
      )
      .slice(0, kind === "DRIVER" ? 5 : 2)
      .map((a) => a.id),
  );
  const draft = {
    ...team,
    selected,
    initial: true,
    completed: false,
    carry: 0,
    chips: [],
    active: "",
    restore: [],
    allowPenalties: false,
  };
  validateTeam(dataset, draft);
  return {
    dataset: { ...dataset, rounds: dataset.rounds.slice(0, 1) },
    team: draft,
  };
}
