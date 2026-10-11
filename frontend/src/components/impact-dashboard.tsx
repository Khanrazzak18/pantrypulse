"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ApiRequestError, apiFetch, LONG_TIMEOUT_MS } from "@/lib/api/client";
import { CATEGORY_LABELS } from "@/lib/donations";
import {
  addWeeks,
  formatInt,
  formatLb,
  formatPct,
  type Metrics,
  PRESETS,
  presetStart,
  type RefreshResult,
  shortDate,
} from "@/lib/dashboard";

import { dateRangeError, MAX_DATE, MIN_DATE } from "@/lib/text";

import { SummaryEditor } from "./summary-editor";

const inputClass =
  "rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm shadow-sm outline-none focus:border-green-700 focus:ring-2 focus:ring-green-200";
const COLORS = { green: "#15803d", amber: "#d97706", stone: "#57534e", red: "#b91c1c" };
const catLabel = (c: string) => (CATEGORY_LABELS as Record<string, string>)[c] ?? c;

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <p className="text-sm text-stone-600" suppressHydrationWarning>
      {now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
      {" · "}
      {now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })}
    </p>
  );
}

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-4">
      <dt className="text-sm text-stone-500">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
      {note && <p className="mt-0.5 text-xs text-stone-500">{note}</p>}
    </div>
  );
}

function ChartCard({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 className="font-semibold">{title}</h2>
      {hint && <p className="text-xs text-stone-500">{hint}</p>}
      <div className="mt-3 h-56">{children}</div>
    </section>
  );
}

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

type Loaded = { key: string; metrics?: Metrics; error?: string };

export function ImpactDashboard({ initial }: { initial: Metrics }) {
  const { data_start: dataStart, data_end: dataEnd } = initial.range;
  const [start, setStart] = useState(initial.range.start);
  const [end, setEnd] = useState(initial.range.end);
  const [loaded, setLoaded] = useState<Loaded>({ key: `${initial.range.start}|${initial.range.end}|0`, metrics: initial });
  const [refresh, setRefresh] = useState<
    { kind: "idle" } | { kind: "running" } | { kind: "done"; result: RefreshResult } | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [reload, setReload] = useState(0);

  const key = `${start}|${end}|${reload}`;
  const rangeError =
    dateRangeError(start) ?? dateRangeError(end) ??
    (start > end
      ? "The start date must not be after the end date."
      : (Date.parse(end) - Date.parse(start)) / 86_400_000 > 260 * 7
        ? "Choose a range of at most 260 weeks (5 years)."
        : null);
  useEffect(() => {
    if (rangeError) return;
    let cancelled = false;
    apiFetch<Metrics>(`/api/dashboard/metrics?start=${start}&end=${end}`)
      .then((metrics) => !cancelled && setLoaded({ key, metrics }))
      .catch((err: unknown) => !cancelled && setLoaded({ key, error: err instanceof Error ? err.message : "Could not load the dashboard." }));
    return () => {
      cancelled = true;
    };
  }, [key, start, end, rangeError]);

  const current = loaded.key === key;
  const loading = !rangeError && !current;
  const m = current ? loaded.metrics : (loaded.metrics ?? initial);
  const error = current ? loaded.error : undefined;

  async function runRefresh() {
    setRefresh({ kind: "running" });
    try {
      const result = await apiFetch<RefreshResult>("/api/admin/jobs/weekly-refresh", { method: "POST" }, LONG_TIMEOUT_MS);
      setRefresh({ kind: "done", result });
    } catch (err) {
      setRefresh({ kind: "error", message: err instanceof ApiRequestError || err instanceof Error ? err.message : "Something went wrong." });
    }
  }

  const weekly = (m?.weekly ?? []).map((w) => ({ ...w, label: shortDate(w.week_start) }));
  const empty = m != null && m.totals.pantry_weeks === 0 && m.totals.shortage_reports === 0 && m.totals.received_perishable_lbs === 0;
  const categories = (m?.by_category ?? []).map((c) => ({ ...c, name: catLabel(c.category) }));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Impact dashboard</h1>
          <Clock />
        </div>
        <button
          type="button"
          onClick={() => void runRefresh()}
          disabled={refresh.kind === "running"}
          className="flex items-center gap-2 rounded-md bg-green-700 px-4 py-2 font-medium text-white hover:bg-green-800 disabled:opacity-70"
        >
          {refresh.kind === "running" && <Spinner />}
          {refresh.kind === "running" ? "Refreshing…" : "Run weekly refresh"}
        </button>
      </div>

      {refresh.kind === "running" && (
        <p role="status" className="rounded-md border border-stone-200 bg-stone-50 p-3 text-sm text-stone-700">
          Training the forecast and re-running allocation. This takes about 15 seconds.
        </p>
      )}
      {refresh.kind === "done" && (
        <p role="status" className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-900">
          Done in {refresh.result.total_seconds} s: forecast for the week of {shortDate(refresh.result.week_start)} and{" "}
          {refresh.result.proposed_rows.toLocaleString("en-US")} proposed shipments ready on the Allocations page.
        </p>
      )}
      {refresh.kind === "error" && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {refresh.message}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="from" className="mb-1 block text-xs font-medium">From</label>
          <input id="from" type="date" className={inputClass} value={start} min={MIN_DATE} max={MAX_DATE} onChange={(e) => e.target.value && setStart(e.target.value)} />
        </div>
        <div>
          <label htmlFor="to" className="mb-1 block text-xs font-medium">To</label>
          <input id="to" type="date" className={inputClass} value={end} min={MIN_DATE} max={MAX_DATE} onChange={(e) => e.target.value && setEnd(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-2">
          {dataEnd &&
            PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm hover:bg-stone-50"
                onClick={() => {
                  setEnd(dataEnd);
                  setStart(presetStart(dataEnd, p.weeks) ?? dataStart ?? addWeeks(dataEnd, -25));
                }}
              >
                {p.label}
              </button>
            ))}
        </div>
      </div>
      {rangeError && <p role="alert" className="text-sm text-red-700">{rangeError}</p>}
      {error && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}{" "}
          <button type="button" className="font-medium underline" onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </p>
      )}

      {m && (
        <div className={loading ? "opacity-60 transition-opacity" : ""} aria-busy={loading}>
          {loading && <p role="status" className="mb-2 text-sm text-stone-500">Loading…</p>}
          {empty ? (
            <p className="rounded-lg border border-dashed border-stone-300 p-8 text-center text-stone-600">
              No distributions, shortage reports or lots in this date range.
            </p>
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Kpi label="Perishable spoilage" value={formatPct(m.totals.spoilage_pct)} note={`${formatLb(m.totals.expired_perishable_lbs)} of ${formatLb(m.totals.received_perishable_lbs)}`} />
                <Kpi label="Pantry-weeks with a shortage" value={formatPct(m.totals.stockout_pct)} note={`${formatInt(m.totals.shortage_reports)} reports`} />
                <Kpi label="Pounds distributed" value={formatLb(m.totals.lbs_distributed)} />
                <Kpi label="Households served" value={formatInt(m.totals.households_served)} note="counted once per pantry-week" />
              </dl>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <ChartCard title="Spoilage % over time" hint="Expired pounds of perishable lots by the week they arrived">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={weekly}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
                      <XAxis dataKey="label" fontSize={11} interval="preserveStartEnd" />
                      <YAxis fontSize={11} unit="%" width={44} />
                      <Tooltip formatter={(v) => (v == null ? "n/a" : `${Number(v).toFixed(1)}%`)} />
                      <Line type="monotone" dataKey="spoilage_pct" name="Spoilage" stroke={COLORS.red} dot={false} strokeWidth={2} connectNulls />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartCard>
                <ChartCard title="Stockouts over time" hint="Shortage reports, and the share of pantry-weeks with one">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={weekly}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
                      <XAxis dataKey="label" fontSize={11} interval="preserveStartEnd" />
                      <YAxis yAxisId="n" fontSize={11} width={44} />
                      <YAxis yAxisId="p" orientation="right" fontSize={11} unit="%" width={44} />
                      <Tooltip />
                      <Legend />
                      <Line yAxisId="n" type="monotone" dataKey="shortage_reports" name="Reports" stroke={COLORS.amber} dot={false} strokeWidth={2} />
                      <Line yAxisId="p" type="monotone" dataKey="stockout_pct" name="Pantry-weeks short %" stroke={COLORS.stone} dot={false} strokeWidth={2} connectNulls />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartCard>
                <ChartCard title="Pounds distributed over time">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={weekly}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
                      <XAxis dataKey="label" fontSize={11} interval="preserveStartEnd" />
                      <YAxis fontSize={11} width={56} tickFormatter={(v) => Number(v).toLocaleString("en-US")} />
                      <Tooltip formatter={(v) => formatLb(Number(v))} />
                      <Bar dataKey="lbs_distributed" name="Pounds" fill={COLORS.green} />
                    </BarChart>
                  </ResponsiveContainer>
                </ChartCard>
                <ChartCard title="Households served over time" hint="Once per pantry-week">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={weekly}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
                      <XAxis dataKey="label" fontSize={11} interval="preserveStartEnd" />
                      <YAxis fontSize={11} width={56} tickFormatter={(v) => Number(v).toLocaleString("en-US")} />
                      <Tooltip formatter={(v) => formatInt(Number(v))} />
                      <Line type="monotone" dataKey="households_served" name="Households" stroke={COLORS.green} dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartCard>
              </div>

              <section className="mt-4 rounded-lg border border-stone-200 bg-white p-4">
                <h2 className="font-semibold">By category</h2>
                <div className="mt-3 h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={categories} layout="vertical" margin={{ left: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
                      <XAxis type="number" fontSize={11} tickFormatter={(v) => Number(v).toLocaleString("en-US")} />
                      <YAxis type="category" dataKey="name" fontSize={11} width={80} />
                      <Tooltip formatter={(v) => formatLb(Number(v))} />
                      <Bar dataKey="lbs_distributed" name="Pounds distributed" fill={COLORS.green} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-stone-500">
                      <tr><th className="py-1 pr-4 font-medium">Category</th><th className="py-1 pr-4 font-medium">Pounds</th><th className="py-1 pr-4 font-medium">Shortage reports</th><th className="py-1 font-medium">Spoilage</th></tr>
                    </thead>
                    <tbody>
                      {categories.map((c) => (
                        <tr key={c.category} className="border-t border-stone-100">
                          <td className="py-1 pr-4">{c.name}</td>
                          <td className="py-1 pr-4 tabular-nums">{formatLb(c.lbs_distributed)}</td>
                          <td className="py-1 pr-4 tabular-nums">{c.shortage_reports}</td>
                          <td className="py-1 tabular-nums">{c.spoilage_pct == null ? "n/a" : formatPct(c.spoilage_pct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      )}

      {dataEnd && <SummaryEditor dataStart={dataStart ?? dataEnd} dataEnd={dataEnd} />}
    </div>
  );
}
