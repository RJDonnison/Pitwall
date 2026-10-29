import { validateDataset } from "./optimizer.js";

export async function fetchDataset() {
  const url = new URL(
    `${import.meta.env.BASE_URL}forecast.json`,
    location.href,
  );
  url.searchParams.set("at", Date.now());
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok)
    throw new Error(
      "Published forecasts are not available. Run the forecast publishing workflow.",
    );
  return validateDataset(await response.json());
}

// Pages cannot bypass the official site's CORS policy. A failed network request
// is distinct from a successful request exposing changed prices/roster/locks.
export async function verifyLive(data) {
  const base = "https://fantasy.formula1.com/feeds/";
  let bodies;
  try {
    bodies = await Promise.all(
      [
        `drivers/${data.price_gameday_id}_en.json`,
        "v2/statistics/driverconstructors_4.json",
        "v2/schedule/raceday_en.json",
      ].map(async (path) => {
        const response = await fetch(`${base}${path}?at=${Date.now()}`, {
          cache: "no-store",
          credentials: "omit",
          signal: AbortSignal.timeout(7000),
        });
        if (!response.ok) throw new Error("Official data request failed");
        const body = await response.json();
        if (!body?.Data || body.Meta?.Success === false)
          throw new Error("Unrecognized official data");
        return body.Data;
      }),
    );
  } catch {
    return {
      verified: false,
      message:
        "The official feeds cannot be verified from this browser. This is a published-snapshot preview.",
    };
  }
  const [feed, statistics, schedule] = bodies;
  const rows = feed.Value?.filter((r) => String(r.IsActive) === "1");
  if (
    !rows ||
    rows.length !== data.assets.length ||
    Number(statistics.season) !== data.season
  )
    throw new Error(
      "The live season or roster changed. Refresh published forecasts before planning.",
    );
  for (const a of data.assets) {
    const row = rows.find((r) => String(r.PlayerId) === a.id);
    const blocks = statistics[a.kind === "DRIVER" ? "driver" : "constructor"];
    const stat = blocks
      ?.find((b) => b.config?.key === "fPoints")
      ?.participants?.find((r) => String(r.playerid) === a.id);
    const price = Number(row?.Value) * 10;
    const statisticsPrice = Number(stat?.curvalue) * 10;
    if (
      !row ||
      row.PositionName !== a.kind ||
      !Number.isFinite(price) ||
      Math.abs(price - a.price_tenths_m) > 1e-6 ||
      !stat ||
      !Number.isFinite(statisticsPrice) ||
      Math.abs(statisticsPrice - a.price_tenths_m) > 1e-6
    )
      throw new Error(
        "Live prices differ from the published forecasts. Wait for a new publication.",
      );
  }
  const fixtures = schedule.fixtures?.filter(
    (f) =>
      Number(f.Season) === data.season &&
      Number(f.GamedayId) === data.price_gameday_id &&
      Number(f.IsPostponed) === 0,
  );
  if (
    !fixtures?.length ||
    fixtures.some((f) =>
      [f.GDIsLocked, f.MDIsLocked, f.MHIsLocked].some(
        (v) => !["0", 0].includes(v),
      ),
    )
  )
    throw new Error(
      "The current game is locked or its lock state cannot be verified.",
    );
  return {
    verified: true,
    message:
      "Live roster and prices match; account settings are entered manually.",
  };
}
