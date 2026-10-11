"use client";

import { useRouter } from "next/navigation";

import { ErrorPanel } from "./error-panel";

export function UnavailableView({ from }: { from: string }) {
  const router = useRouter();
  return (
    <ErrorPanel
      title="PantryPulse is temporarily unavailable"
      message="We can't reach our data right now. Nothing you did has been lost. Please try again in a moment."
      onRetry={() => router.replace(from)}
      home={false}
    />
  );
}
