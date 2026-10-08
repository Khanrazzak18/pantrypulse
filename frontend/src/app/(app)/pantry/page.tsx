import type { Metadata } from "next";

import { PantryPortal } from "@/components/pantry-portal";
import { requireRole } from "@/lib/auth";
import type { Deliveries, ShortageReport } from "@/lib/pantry";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "My pantry · PantryPulse" };

export default async function MyPantryPage() {
  await requireRole(["pantry_manager"], "/pantry");
  const [deliveries, reports] = await Promise.all([
    serverJson<Deliveries>("/api/pantry/deliveries", "/pantry"),
    serverJson<ShortageReport[]>("/api/pantry/shortage-reports", "/pantry"),
  ]);
  return <PantryPortal initialDeliveries={deliveries} initialReports={reports} />;
}
