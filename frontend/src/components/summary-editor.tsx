"use client";

import { useEffect, useState } from "react";

import { ApiRequestError, apiFetch, LONG_TIMEOUT_MS } from "@/lib/api/client";
import { controlCharError } from "@/lib/text";
import { monthLabel, monthsBetween, type Summary } from "@/lib/dashboard";

const message = (err: unknown) => (err instanceof ApiRequestError || err instanceof Error ? err.message : "Something went wrong.");

export function SummaryEditor({ dataStart, dataEnd }: { dataStart: string; dataEnd: string }) {
  const months = monthsBetween(dataStart.slice(0, 7), dataEnd.slice(0, 7));
  const [month, setMonth] = useState(months[0] ?? "");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "drafting" | "approving">("idle");
  const [error, setError] = useState<string | null>(null);

  const [loadedMonth, setLoadedMonth] = useState<string | null>(null);

  // "Loading" is simply "the data on screen is not for the selected month".
  useEffect(() => {
    if (!month) return;
    let cancelled = false;
    apiFetch<{ summary: Summary | null }>(`/api/dashboard/summaries/${month}`)
      .then((out) => {
        if (cancelled) return;
        setSummary(out.summary);
        setText(out.summary ? (out.summary.final_text ?? out.summary.ai_draft) : "");
        setError(null);
        setLoadedMonth(month);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(message(err));
        setLoadedMonth(month);
      });
    return () => {
      cancelled = true;
    };
  }, [month]);

  async function draft() {
    setState("drafting");
    setError(null);
    try {
      const out = await apiFetch<Summary>(`/api/dashboard/summaries/${month}/draft`, { method: "POST" }, LONG_TIMEOUT_MS);
      setSummary(out);
      setText(out.ai_draft);
    } catch (err) {
      setError(message(err));
    } finally {
      setState("idle");
    }
  }

  async function approve() {
    if (!text.trim()) {
      setError("Write the summary text before approving.");
      return;
    }
    const bad = controlCharError(text, true);
    if (bad) {
      setError(bad);
      return;
    }
    setState("approving");
    setError(null);
    try {
      const out = await apiFetch<Summary>(`/api/dashboard/summaries/${month}/approve`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      setSummary(out);
      setText(out.final_text ?? "");
    } catch (err) {
      setError(message(err));
    } finally {
      setState("idle");
    }
  }

  const approved = summary?.status === "approved";
  const loading = loadedMonth !== month;
  const busy = state !== "idle" || loading;

  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4" aria-labelledby="summary-h">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="summary-h" className="font-semibold">Monthly summary for grant reports</h2>
          <p className="text-sm text-stone-600">
            The AI sees only the month&apos;s totals, never individual records. You edit and approve the final text.
          </p>
        </div>
        <div>
          <label htmlFor="month" className="mb-1 block text-xs font-medium">Month</label>
          <select id="month" value={month} onChange={(e) => setMonth(e.target.value)} disabled={busy} className="rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm">
            {months.map((m) => (
              <option key={m} value={m}>{monthLabel(m)}</option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
          {!approved && (
            <>
              {" "}
              <button type="button" className="font-medium underline" onClick={() => void draft()} disabled={busy}>
                Try the AI again
              </button>
            </>
          )}
        </p>
      )}

      {loading ? (
        <p role="status" className="mt-3 text-sm text-stone-500">Loading…</p>
      ) : (
        <div className="mt-3 space-y-3">
          {approved && (
            <p role="status" className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-900">
              Approved and final{summary?.approved_at ? ` (${new Date(summary.approved_at).toLocaleDateString("en-US")})` : ""}.
            </p>
          )}
          {!summary && !error && (
            <p className="text-sm text-stone-600">No summary for {monthLabel(month)} yet. Draft one with the AI, or write your own below.</p>
          )}
          <label htmlFor="summary-text" className="sr-only">Summary text</label>
          <textarea
            id="summary-text"
            rows={7}
            value={text}
            onChange={(e) => setText(e.target.value)}
            readOnly={approved}
            maxLength={4000}
            className="block w-full rounded-md border border-stone-300 px-3 py-2 text-sm shadow-sm outline-none focus:border-green-700 focus:ring-2 focus:ring-green-200 read-only:bg-stone-50"
          />
          {!approved && (
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void draft()} disabled={busy} className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm hover:bg-stone-50 disabled:opacity-60">
                {state === "drafting" ? "Drafting…" : summary?.ai_draft ? "Draft again with AI" : "Draft with AI"}
              </button>
              <button type="button" onClick={() => void approve()} disabled={busy} className="rounded-md bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-800 disabled:opacity-60">
                {state === "approving" ? "Saving…" : "Approve as final"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
