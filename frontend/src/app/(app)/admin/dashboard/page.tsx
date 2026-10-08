import type { Metadata } from "next";

import { ImpactDashboard } from "@/components/impact-dashboard";
import { requireRole } from "@/lib/auth";
import type { Metrics } from "@/lib/dashboard";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "Impact dashboard · PantryPulse" };

export default async function DashboardPage() {
  const here = "/admin/dashboard";
  await requireRole(["admin"], here);
  const metrics = await serverJson<Metrics>("/api/dashboard/metrics", here);
  return <ImpactDashboard initial={metrics} />;
}
