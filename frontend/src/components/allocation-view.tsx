"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { ApiRequestError, apiFetch } from "@/lib/api/client";
import {
  type Allocation,
  type AllocationList,
  type AllocationRun,
  expiryLabel,
  type Filters,
  formatLbs,
  groupByPantry,
  matchesFilters,
  shownLbs,
  STATUS_TABS,
  statusLabel,
  validateEditLbs,
} from "@/lib/allocations";
import { CATEGORY_LABELS } from "@/lib/donations";
import { formatRunTime, weekLabel } from "@/lib/forecasts";

type Notice = { kind: "info" | "success" | "error"; message: string } | null;

const NOTICE_STYLES = {
  info: "border-stone-200 bg-stone-50 text-stone-700",
  success: "border-green-300 bg-green-50 text-green-900",
  error: "border-red-300 bg-red-50 text-red-900",
};
const inputClass =
  "block w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm shadow-sm outline-none focus:border-green-700 focus:ring-2 focus:ring-green-200";
const STATUS_STYLES: Record<string, string> = {
  proposed: "bg-amber-100 text-amber-900",
  approved: "bg-green-100 text-green-900",
  edited: "bg-sky-100 text-sky-900",
  rejected: "bg-stone-200 text-stone-700",
};

function message(err: unknown): string {
  return err instanceof ApiRequestError || err instanceof Error ? err.message : "Something went wrong.";
}

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function AllocationView({ initial }: { initial: AllocationList }) {
  const [data, setData] = useState<AllocationList>(initial);
  const [filters, setFilters] = useState<Filters>({ status: "proposed", county: "", search: "" });
  const [busy, setBusy] = useState<string | null>(null); // what the page is waiting on
  const [notice, setNotice] = useState<Notice>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const confirmRef = useRef<HTMLDialogElement>(null);

  const reload = useCallback(async () => {
    try {
      setData(await apiFetch<AllocationList>("/api/allocations"));
      setLoadError(null);
    } catch (err) {
      setLoadError(message(err));
    }
  }, []);

  const run = data.run as AllocationRun | null;
  const counties = useMemo(() => [...new Set(data.rows.map((r) => r.pantry.county))].sort(), [data.rows]);
  const shown = useMemo(() => data.rows.filter((r) => matchesFilters(r, filters)), [data.rows, filters]);
  const groups = useMemo(() => groupByPantry(shown), [shown]);
  const shownProposed = shown.filter((r) => r.status === "proposed");
  const shownProposedLbs = shownProposed.reduce((sum, r) => sum + r.recommended_lbs, 0);
  const templateCount = data.rows.filter((r) => r.status === "proposed" && r.reason_source === "template").length;

  async function act(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setNotice(null);
    try {
      const done = await fn();
      if (done) setNotice({ kind: "success", message: done });
    } catch (err) {
      setNotice({ kind: "error", message: message(err) });
    } finally {
      await reload();
      setBusy(null);
    }
  }

  const runAllocation = () =>
    act("run", async () => {
      const started = performance.now();
      const result = await apiFetch<AllocationRun>("/api/allocations/run", { method: "POST" });
      const seconds = ((performance.now() - started) / 1000).toFixed(1);
      return `Proposed ${result.rows.toLocaleString("en-US")} shipments for the week of ${weekLabel(result.week_start)} in ${seconds} s.`;
    });

  const bulkApprove = () => {
    confirmRef.current?.close();
    const ids = shownProposed.map((r) => r.id);
    return act("bulk", async () => {
      const result = await apiFetch<{ approved: number; approved_lbs: number }>("/api/allocations/bulk-approve", {
        method: "POST",
        body: JSON.stringify({ ids }),
      });
      return `Approved ${result.approved.toLocaleString("en-US")} shipments (${formatLbs(result.approved_lbs)}).`;
    });
  };

  const moreReasons = () =>
    act("reasons", async () => {
      if (!run) return;
      const result = await apiFetch<AllocationRun>(`/api/allocations/runs/${run.id}/reasons`, { method: "POST" });
      return `${result.reasons_ai.toLocaleString("en-US")} of ${result.rows.toLocaleString("en-US")} reasons are now written by the AI.`;
    });

  const decide = (row: Allocation, action: "approve" | "reject") =>
    act(`row-${row.id}`, async () => {
      await apiFetch(`/api/allocations/${row.id}/${action}`, { method: "POST" });
    });

  const saveEdit = (row: Allocation, lbs: number, note: string) =>
    act(`row-${row.id}`, async () => {
      await apiFetch(`/api/allocations/${row.id}/edit`, {
        method: "POST",
        body: JSON.stringify({ lbs, note: note || null }),
      });
    });

  const summary = data.summary;
  const noRun = run === null && data.rows.length === 0 && busy !== "run";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Allocations</h1>
          <p className="mt-1 text-stone-600">
            Which lots go to which pantries this week, soonest-expiring food first. Nothing is sent until you approve it.
          </p>
          <p className="mt-1 text-sm text-stone-500">
            {run
              ? `Week of ${weekLabel(run.week_start)} · delivery ${weekLabel(run.delivery_date)} · last run ${formatRunTime(run.created_at)}.`
              : "No allocation has been run yet."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void runAllocation()}
          disabled={busy !== null}
          className="flex items-center gap-2 rounded-md bg-green-700 px-4 py-2 font-medium text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {busy === "run" && <Spinner />}
          {busy === "run" ? "Calculating…" : run ? "Run again" : "Run allocation"}
        </button>
      </div>

      {busy === "run" && (
        <p role="status" className="rounded-md border border-stone-200 bg-stone-50 p-3 text-sm text-stone-700">
          Matching stock to forecast demand and writing reasons. This takes a few seconds.
        </p>
      )}
      {notice && (
        <p role={notice.kind === "error" ? "alert" : "status"} className={`rounded-md border p-3 text-sm ${NOTICE_STYLES[notice.kind]}`}>
          {notice.message}
        </p>
      )}
      {loadError && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          Could not refresh the list: {loadError}{" "}
          <button type="button" className="font-medium underline" onClick={() => void reload()}>
            Try again
          </button>
        </p>
      )}

      {noRun ? (
        <div className="rounded-md border border-dashed border-stone-300 p-8 text-center text-stone-600">
          <p className="font-medium">Nothing to review yet.</p>
          <p className="mt-1 text-sm">
            Run the forecast, make sure donations are confirmed, then choose &ldquo;Run allocation&rdquo;.
          </p>
        </div>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["To review", `${summary.proposed.toLocaleString("en-US")} · ${formatLbs(summary.proposed_lbs)}`],
              ["Approved", `${(summary.approved + summary.edited).toLocaleString("en-US")} · ${formatLbs(summary.approved_lbs)}`],
              ["Rejected", summary.rejected.toLocaleString("en-US")],
              ["Not offered (expire first)", run ? run.lots_excluded.toLocaleString("en-US") : "0"],
            ].map(([term, value]) => (
              <div key={term} className="rounded-md border border-stone-200 bg-white p-3">
                <dt className="text-xs text-stone-500">{term}</dt>
                <dd className="mt-0.5 font-semibold">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="flex flex-wrap items-end gap-3">
            <div role="tablist" aria-label="Show" className="flex overflow-hidden rounded-md border border-stone-300 text-sm">
              {STATUS_TABS.map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  role="tab"
                  aria-selected={filters.status === tab.value}
                  onClick={() => setFilters({ ...filters, status: tab.value })}
                  className={`px-3 py-1.5 ${filters.status === tab.value ? "bg-green-700 text-white" : "bg-white hover:bg-stone-50"}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="min-w-36">
              <label htmlFor="county" className="mb-1 block text-xs font-medium">County</label>
              <select id="county" className={inputClass} value={filters.county} onChange={(e) => setFilters({ ...filters, county: e.target.value })}>
                <option value="">All counties</option>
                {counties.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="min-w-48 flex-1">
              <label htmlFor="search" className="mb-1 block text-xs font-medium">Search pantry or food</label>
              <input id="search" type="search" className={inputClass} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
            </div>
            <div className="flex flex-wrap gap-2">
              {templateCount > 0 && run && (
                <button
                  type="button"
                  onClick={() => void moreReasons()}
                  disabled={busy !== null}
                  className="flex items-center gap-2 rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm hover:bg-stone-50 disabled:opacity-60"
                >
                  {busy === "reasons" && <Spinner />}
                  Write more AI reasons
                </button>
              )}
              <button
                type="button"
                onClick={() => confirmRef.current?.showModal()}
                disabled={busy !== null || shownProposed.length === 0}
                className="flex items-center gap-2 rounded-md bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === "bulk" && <Spinner />}
                Approve all shown ({shownProposed.length.toLocaleString("en-US")})
              </button>
            </div>
          </div>

          {groups.length === 0 ? (
            <p className="rounded-md border border-dashed border-stone-300 p-6 text-center text-stone-600">
              {data.rows.length === 0
                ? "The last run proposed no shipments: there was no stock that fits the forecast demand."
                : "No shipments match these filters."}
            </p>
          ) : (
            <ul className="space-y-4">
              {groups.map((g) => (
                <li key={g.pantryId} className="rounded-md border border-stone-200 bg-white">
                  <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-stone-200 bg-stone-50 px-4 py-2">
                    <h2 className="font-semibold">{g.name}</h2>
                    <p className="text-sm text-stone-600">
                      {g.county} · {g.miles.toLocaleString("en-US")} mi · {formatLbs(g.totalLbs)} in {g.rows.length} {g.rows.length === 1 ? "lot" : "lots"}
                    </p>
                  </div>
                  <ul className="divide-y divide-stone-100">
                    {g.rows.map((row) => (
                      <AllocationRow key={row.id} row={row} busy={busy} onDecide={decide} onSaveEdit={saveEdit} />
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <dialog ref={confirmRef} className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg p-5 shadow-xl backdrop:bg-black/40">
        <h2 className="text-lg font-semibold">Approve all shown?</h2>
        <p className="mt-2 text-sm text-stone-700">
          This approves {shownProposed.length.toLocaleString("en-US")} shipments ({formatLbs(shownProposedLbs)}) to{" "}
          {new Set(shownProposed.map((r) => r.pantry.id)).size.toLocaleString("en-US")} pantries and takes that food out of stock.
          Only what the filters show is included. Approved shipments can&rsquo;t be undone here.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={() => confirmRef.current?.close()} className="rounded-md border border-stone-300 px-3 py-1.5 text-sm hover:bg-stone-50">
            Cancel
          </button>
          <button type="button" onClick={() => void bulkApprove()} className="rounded-md bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-800">
            Approve {shownProposed.length.toLocaleString("en-US")}
          </button>
        </div>
      </dialog>
    </div>
  );
}

function AllocationRow({
  row,
  busy,
  onDecide,
  onSaveEdit,
}: {
  row: Allocation;
  busy: string | null;
  onDecide: (row: Allocation, action: "approve" | "reject") => void;
  onSaveEdit: (row: Allocation, lbs: number, note: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [lbsText, setLbsText] = useState("");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);
  const error = validateEditLbs(lbsText, row.lot.remaining_lbs);
  const proposed = row.status === "proposed";
  const rowBusy = busy === `row-${row.id}`;
  const urgent = row.lot.days_left != null && row.lot.days_left <= 3;

  function openEdit() {
    setLbsText(String(row.recommended_lbs));
    setNote("");
    setTouched(false);
    setEditing(true);
  }
  function submit() {
    setTouched(true);
    if (error) return;
    onSaveEdit(row, Number(lbsText), note.trim());
    setEditing(false);
  }

  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">
            {formatLbs(shownLbs(row))} of {row.lot.item_name}
            {row.final_lbs != null && row.final_lbs !== row.recommended_lbs && (
              <span className="ml-2 text-sm font-normal text-stone-500">(proposed {formatLbs(row.recommended_lbs)})</span>
            )}
          </p>
          <p className="text-sm text-stone-600">
            {(CATEGORY_LABELS as Record<string, string>)[row.lot.category] ?? row.lot.category} · {row.lot.storage_type} ·{" "}
            <span className={urgent ? "font-medium text-red-700" : ""}>{expiryLabel(row)}</span> · {formatLbs(row.lot.remaining_lbs)} left in lot
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[row.status] ?? ""}`}>{statusLabel(row.status)}</span>
      </div>
      <p className="text-sm text-stone-700">
        {row.reason}{" "}
        <span
          className={`ml-1 rounded px-1.5 py-0.5 text-xs ${row.reason_source === "ai" ? "bg-violet-100 text-violet-900" : "bg-stone-100 text-stone-600"}`}
          title={row.reason_source === "ai" ? "Written by the AI from this row's facts" : "Built from a template"}
        >
          {row.reason_source === "ai" ? "AI" : "Template"}
        </span>
      </p>

      {proposed && !editing && (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy !== null} onClick={() => onDecide(row, "approve")} className="rounded-md bg-green-700 px-3 py-1 text-sm font-medium text-white hover:bg-green-800 disabled:opacity-50">
            {rowBusy ? "Saving…" : "Approve"}
          </button>
          <button type="button" disabled={busy !== null} onClick={openEdit} className="rounded-md border border-stone-300 bg-white px-3 py-1 text-sm hover:bg-stone-50 disabled:opacity-50">
            Edit
          </button>
          <button type="button" disabled={busy !== null} onClick={() => onDecide(row, "reject")} className="rounded-md border border-stone-300 bg-white px-3 py-1 text-sm text-red-800 hover:bg-red-50 disabled:opacity-50">
            Reject
          </button>
        </div>
      )}

      {proposed && editing && (
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="grid gap-2 rounded-md bg-stone-50 p-3 sm:grid-cols-[10rem_1fr_auto] sm:items-start"
        >
          <div>
            <label htmlFor={`lbs-${row.id}`} className="mb-1 block text-xs font-medium">New amount (lb)</label>
            <input
              id={`lbs-${row.id}`}
              inputMode="decimal"
              value={lbsText}
              onChange={(e) => setLbsText(e.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && error !== null}
              aria-describedby={`lbs-err-${row.id}`}
              className={inputClass}
            />
            <p id={`lbs-err-${row.id}`} role="alert" className="mt-1 min-h-4 text-xs text-red-700">
              {touched && error ? error : ""}
            </p>
          </div>
          <div>
            <label htmlFor={`note-${row.id}`} className="mb-1 block text-xs font-medium">Note (optional)</label>
            <input id={`note-${row.id}`} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
          </div>
          <div className="flex gap-2 sm:pt-5">
            <button type="submit" disabled={busy !== null} className="rounded-md bg-green-700 px-3 py-1 text-sm font-medium text-white hover:bg-green-800 disabled:opacity-50">
              Save
            </button>
            <button type="button" onClick={() => setEditing(false)} className="rounded-md border border-stone-300 bg-white px-3 py-1 text-sm hover:bg-stone-50">
              Cancel
            </button>
          </div>
        </form>
      )}
    </li>
  );
}
