import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ReviewForm } from "@/components/review-form";
import { StatusBadge } from "@/components/status-badge";
import type { DonationDetail, Donor } from "@/lib/api/client";
import { requireRole } from "@/lib/auth";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "Review donation · PantryPulse" };

const SOURCES: Record<string, string> = { email: "Email", pdf: "PDF", image: "Photo", text: "Text file", historical: "Imported" };

export default async function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const here = `/coordinator/donations/${id}`;
  await requireRole(["coordinator", "admin"], here);
  const [donation, donors] = await Promise.all([
    serverJson<DonationDetail>(`/api/donations/${id}`, here),
    serverJson<Donor[]>("/api/donors", here),
  ]);

  return (
    <div className="space-y-4">
      <Link href="/coordinator/donations" className="text-sm font-medium text-green-800 hover:underline">
        ← All donations
      </Link>
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{donation.original_filename ?? `Donation ${donation.id}`}</h1>
          <StatusBadge status={donation.status} />
        </div>
        <p className="mt-1 text-sm text-stone-600">
          {SOURCES[donation.source_type] ?? donation.source_type} · received{" "}
          {new Date(donation.received_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          {donation.model_id && (
            <>
              {" "}· read by <code className="text-xs">{donation.model_id}</code>
              {donation.latency_ms ? ` in ${(donation.latency_ms / 1000).toFixed(1)} s` : ""}
              {donation.input_tokens != null ? ` (${donation.input_tokens.toLocaleString("en-US")} tokens in, ${donation.output_tokens?.toLocaleString("en-US")} out)` : ""}
            </>
          )}
        </p>
        {donation.raw_output_cleared_at && (
          <p className="mt-1 text-sm text-stone-600">
            The model&apos;s raw output was cleared on{" "}
            {new Date(donation.raw_output_cleared_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}{" "}
            (90 days after review). The decision and any confirmed items are kept.
          </p>
        )}
      </div>
      <ReviewForm donation={donation} donors={donors} />
    </div>
  );
}
