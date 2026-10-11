import type { Metadata } from "next";

import { UnavailableView } from "@/components/unavailable-view";

export const metadata: Metadata = { title: "Temporarily unavailable · PantryPulse" };

export default async function UnavailablePage({ searchParams }: { searchParams: Promise<{ from?: string }> }) {
  const { from } = await searchParams;
  // Only a path on this site: never send someone to another address.
  const safe = from && from.startsWith("/") && !from.startsWith("//") && !from.includes("\\") ? from : "/";
  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <UnavailableView from={safe} />
    </main>
  );
}
