import { PREWEEK, validateDataset, validateTeam } from "./optimizer.js";

export function rememberWeekend(dataset, team, result) {
  const round = result.rounds[0];
  // A newly published round must not overwrite the unconfirmed previous weekend.
  if (
    team.weekendSuggestion &&
    team.weekendSuggestion.gameday !== round.gameday_id
  )
    return team.weekendSuggestion;
  const selected =
    round.chip === "limitless"
      ? [...(team.active === "limitless" ? team.restore : team.selected)]
      : round.entries.map((e) => e.id);
  const cost =
    round.chip === "limitless"
      ? selected.reduce(
          (sum, id) =>
            sum + dataset.assets.find((a) => a.id === id).price_tenths_m,
          0,
        )
      : round.cost;
  return {
    season: dataset.season,
    gameday: round.gameday_id,
    round: round.round,
    name: round.name,
    end: dataset.rounds[0].last_session_utc,
    selected,
    cash: team.budget - cost,
    carry: round.carry,
    chip: round.chip,
  };
}

export function weekendReady(dataset, saved, now = Date.now()) {
  return Boolean(
    saved &&
    saved.season === dataset.season &&
    dataset.rounds[0].round > saved.round &&
    Number.isFinite(Date.parse(saved.end)) &&
    Date.parse(saved.end) < now,
  );
}

export function adoptWeekend(dataset, team, now = Date.now()) {
  validateDataset(dataset, now);
  const saved = team.weekendSuggestion;
  if (!weekendReady(dataset, saved, now))
    throw new Error(
      "This saved suggestion is available after the weekend has ended and the next round is published.",
    );
  if (
    !Array.isArray(saved.selected) ||
    (saved.chip !== null && !PREWEEK.includes(saved.chip))
  )
    throw new Error(
      "The saved suggestion cannot be verified. Update the team manually.",
    );
  if (
    !Number.isInteger(saved.cash) ||
    saved.cash < 0 ||
    ![0, 1].includes(saved.carry)
  )
    throw new Error(
      "The saved budget or transfer allowance cannot be verified. Update the team manually.",
    );
  const value = saved.selected.reduce((sum, id) => {
    const asset = dataset.assets.find((a) => a.id === id);
    if (!asset)
      throw new Error(
        "A saved selection is no longer active. Update the team manually.",
      );
    return sum + asset.price_tenths_m;
  }, 0);
  const next = {
    ...team,
    selected: [...saved.selected],
    budget: value + saved.cash,
    carry: saved.chip === "limitless" ? 0 : saved.carry,
    chips: team.chips.filter((c) => c !== saved.chip),
    initial: saved.chip === "limitless" && team.limitlessFollowup === true,
    completed: true,
    active: "",
    restore: [],
    weekendSuggestion: null,
  };
  validateTeam(dataset, next);
  return next;
}

const cost = (dataset, ids) =>
  ids.reduce((sum, id) => {
    const asset = dataset.assets.find((a) => a.id === id);
    return asset ? sum + asset.price_tenths_m : NaN;
  }, 0);

// After a race weekend the official game re-prices every asset. The team keeps its
// excess cash, so the budget becomes the new team value plus the unspent cash:
//   budget' = value(new prices) + (budget - value(old prices)).
// `team.valued` remembers the cash against the price gameday it was measured at.
// Within a gameday it is re-measured on every load, so manual budget or roster
// edits are never overwritten; it is only applied when prices move to a later gameday.
export function rollBudget(dataset, team) {
  const gameday = dataset.price_gameday_id;
  const eligible =
    Number.isInteger(gameday) &&
    team.selected.length === 7 &&
    team.active !== "limitless" &&
    !team.initial;
  const value = eligible ? cost(dataset, team.selected) : NaN;
  if (!Number.isFinite(value)) return { team, change: null };
  const prior = team.valued;
  if (
    prior &&
    Number.isInteger(prior.gameday) &&
    prior.gameday < gameday &&
    Number.isInteger(prior.cash) &&
    prior.cash >= 0
  ) {
    const budget = value + prior.cash;
    return {
      team: {
        ...team,
        budget,
        valued: { gameday, cash: prior.cash },
        budgetUpdate: {
          gameday,
          valueFrom: prior.value ?? null,
          valueTo: value,
          cash: prior.cash,
          budgetFrom: team.budget,
          budgetTo: budget,
        },
      },
      change: true,
    };
  }
  const cash = team.budget - value;
  if (cash < 0) return { team, change: null };
  if (prior && prior.gameday === gameday && prior.cash === cash && prior.value === value)
    return { team, change: null };
  return { team: { ...team, valued: { gameday, cash, value } }, change: null };
}
