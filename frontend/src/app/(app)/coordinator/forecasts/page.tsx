import type { Metadata } from "next";

import { ForecastView } from "@/components/forecast-view";
import type { Pantry } from "@/lib/api/client";
import { requireRole } from "@/lib/auth";
import type { LatestRuns } from "@/lib/forecasts";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "Forecasts · PantryPulse" };

export default async function ForecastsPage() {
  const here = "/coordinator/forecasts";
  await requireRole(["coordinator", "admin"], here);
  const [pantries, runs] = await Promise.all([
    serverJson<Pantry[]>("/api/pantries", here),
    serverJson<LatestRuns>("/api/forecasts/runs/latest", here),
  ]);
  return <ForecastView pantries={pantries} initialRuns={runs} />;
}
