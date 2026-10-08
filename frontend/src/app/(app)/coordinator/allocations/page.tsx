import type { Metadata } from "next";

import { AllocationView } from "@/components/allocation-view";
import { requireRole } from "@/lib/auth";
import type { AllocationList } from "@/lib/allocations";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "Allocations · PantryPulse" };

export default async function AllocationsPage() {
  const here = "/coordinator/allocations";
  await requireRole(["coordinator", "admin"], here);
  const initial = await serverJson<AllocationList>("/api/allocations", here);
  return <AllocationView initial={initial} />;
}
