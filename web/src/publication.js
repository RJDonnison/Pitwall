import {
  CARRIED_MODES,
  isRoundUnderway,
  validateDataset,
} from "./optimizer.js";

const SIX_HOURS = 6 * 3600000;

// Rounds that have started or locked cannot be planned. A carried-forward
// forecast was published before they did, so drop them here instead of failing.
// The weekend still in progress is the exception: it stays first until its race
// has finished, rather than the page jumping ahead to the next round.
function openRounds(data, now) {
  const rounds = (data.rounds || []).filter(
    (r) =>
      (Date.parse(r.first_session_utc) > now && !r.locked) ||
      isRoundUnderway(data, r, now),
  );
  return { ...data, rounds };
}

// Never show a blank page because a forecast is old: an old forecast is marked
// as such and still displayed. Only a forecast that is structurally unusable fails.
export function prepare(json, now = Date.now()) {
  let data = json;
  const age = now - Date.parse(data?.generated_at);
  if (
    data?.status === "ready" &&
    !CARRIED_MODES.includes(data.publication_state?.mode) &&
    age > SIX_HOURS
  )
    data = {
      ...data,
      publication_state: {
        ...(data.publication_state || {}),
        mode: "stale",
        reason: "The newest forecasts could not be published yet.",
      },
    };
  if (CARRIED_MODES.includes(data?.publication_state?.mode))
    data = openRounds(data, now);
  return validateDataset(data, now);
}

const stamp = (value) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "an earlier update";

// Tells the reader what the numbers are: live, still updating through practice,
// paused until the race ends, or the last good copy because a refresh failed.
export function bannerText(dataset) {
  const state = dataset.publication_state;
  if (!state) return "";
  const updated = `Last updated ${stamp(dataset.generated_at)}.`;
  if (state.state === "paused")
    return `Predictions are paused for ${state.weekend || "this weekend"} from qualifying and resume after the race. ${updated}`;
  if (state.mode === "carried_forward")
    return `Showing the last published forecasts while the next round's data is not available yet. ${updated}`;
  if (state.mode === "stale" || state.mode === "cached")
    return `${state.reason || "Showing the last available forecasts."} ${updated}`;
  if (state.state === "practice")
    return `Forecasts update after each practice session until qualifying (${(state.practice_sessions || []).join(", ") || "no session finished yet"}). ${updated}`;
  return "";
}
