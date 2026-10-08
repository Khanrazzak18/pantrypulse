"use client";

import { useEffect, useState } from "react";

type Health = { status: string; database: string };
type State =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

export default function Home() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body?.error?.message ?? "API unavailable");
        setState({ kind: "ok", health: body as Health });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: err instanceof Error ? err.message : "API unavailable" });
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <h1 className="text-2xl font-semibold">PantryPulse</h1>
      <p className="mt-1 text-stone-600">AI food allocation for Harvest Bridge Food Bank.</p>
      <section className="mt-8 rounded-lg border border-stone-200 bg-white p-4" aria-live="polite">
        <h2 className="text-sm font-medium uppercase tracking-wide text-stone-500">System status</h2>
        {state.kind === "loading" && <p className="mt-2">Checking API…</p>}
        {state.kind === "ok" && (
          <p className="mt-2 text-green-700">
            API: {state.health.status} · Database: {state.health.database}
          </p>
        )}
        {state.kind === "error" && <p className="mt-2 text-red-700">API error: {state.message}</p>}
      </section>
    </main>
  );
}
