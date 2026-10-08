"use client";

import { useEffect, useState } from "react";

import { ApiRequestError, apiFetch, type Pantry } from "@/lib/api/client";
import { CATEGORIES, CATEGORY_LABELS } from "@/lib/donations";
import {
  type ForecastRun,
  type ForecastSeries,
  formatPercent,
  formatPounds,
  formatRunTime,
  hasForecast,
  improvement,
  type LatestRuns,
  weekLabel,
} from "@/lib/forecasts";

import { ForecastChart } from "./forecast-chart";

type Loaded = { key: string; series?: ForecastSeries; error?: string };
type RunState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "done"; message: string }
  | { kind: "error"; message: string };

const selectClass =
  "block w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm shadow-sm outline-none focus:border-green-700 focus:ring-2 focus:ring-green-200";

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function ForecastView({ pantries, initialRuns }: { pantries: Pantry[]; initialRuns: LatestRuns }) {
  const [pantryId, setPantryId] = useState(String(pantries[0]?.id ?? ""));
  const [category, setCategory] = useState<string>("produce");
  const [showLastYear, setShowLastYear] = useState(false);
  const [runs, setRuns] = useState(initialRuns);
  const [refresh, setRefresh] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [run, setRun] = useState<RunState>({ kind: "idle" });

  // The chart reloads whenever the filters (or a new forecast) change. "Loading" is simply "the
  // data on screen is not for the current key", so no state is set synchronously in the effect.
  const key = `${pantryId}|${category}|${refresh}`;
  useEffect(() => {
    if (!pantryId) return;
    let cancelled = false;
    apiFetch<ForecastSeries>(
      `/api/forecasts/series?pantry_id=${pantryId}&category=${category}&history_weeks=26`,
    )
      .then((series) => !cancelled && setLoaded({ key, series }))
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoaded({ key, error: err instanceof Error ? err.message : "Could not load the forecast." });
      });
    return () => {
      cancelled = true;
    };
  }, [key, pantryId, category]);

  const loading = pantryId !== "" && loaded?.key !== key;
  const series = loaded?.key === key ? loaded.series : undefined;
  const error = loaded?.key === key ? loaded.error : undefined;
  const pantry = pantries.find((p) => String(p.id) === pantryId);

  async function runForecast() {
    setRun({ kind: "running" });
    const started = performance.now();
    try {
      const result = await apiFetch<ForecastRun>("/api/forecasts/run", { method: "POST" });
      const seconds = ((performance.now() - started) / 1000).toFixed(1);
      setRun({
        kind: "done",
        message: `Forecast for the week of ${weekLabel(result.horizon_week_start)} saved in ${seconds} s (${result.rows.toLocaleString("en-US")} forecasts).`,
      });
      setRuns(await apiFetch<LatestRuns>("/api/forecasts/runs/latest"));
      setRefresh((n) => n + 1);
    } catch (err) {
      setRun({
        kind: "error",
        message: err instanceof ApiRequestError || err instanceof Error ? err.message : "Something went wrong.",
      });
    }
  }

  const backtest = runs.backtest;
  const forward = runs.forward;
  const points = series?.points ?? [];
  const acc = series?.accuracy;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Forecasts</h1>
          <p className="mt-1 text-stone-600">
            Expected weekly demand per pantry and food category, with a likely range.
          </p>
          <p className="mt-1 text-sm text-stone-500">
            {forward
              ? `Latest forecast: week of ${weekLabel(forward.horizon_week_start)}, run ${formatRunTime(forward.created_at)}.`
              : "No forecast has been run yet."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void runForecast()}
          disabled={run.kind === "running"}
          className="flex items-center gap-2 rounded-md bg-green-700 px-4 py-2 font-medium text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {run.kind === "running" && <Spinner />}
          {run.kind === "running" ? "Training the model…" : forward ? "Run forecast again" : "Run forecast"}
        </button>
      </div>

      {run.kind === "running" && (
        <p role="status" className="rounded-md border border-stone-200 bg-stone-50 p-3 text-sm text-stone-700">
          Training on the full history and forecasting next week. This takes a few seconds.
        </p>
      )}
      {run.kind === "done" && (
        <p role="status" className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-900">
          {run.message}
        </p>
      )}
      {run.kind === "error" && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {run.message}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="pantry" className="mb-1 block text-sm font-medium">
            Pantry
          </label>
          <select id="pantry" value={pantryId} onChange={(e) => setPantryId(e.target.value)} className={selectClass}>
            {pantries.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.county}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="category" className="mb-1 block text-sm font-medium">
            Category
          </label>
          <select id="category" value={category} onChange={(e) => setCategory(e.target.value)} className={selectClass}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
        </div>
      </div>

      <section aria-labelledby="chart-heading" className="rounded-lg border border-stone-200 bg-white p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="chart-heading" className="text-lg font-semibold">
            {pantry?.name ?? "Pantry"} · {CATEGORY_LABELS[category as keyof typeof CATEGORY_LABELS] ?? category}
          </h2>
          <label className="flex items-center gap-2 text-sm text-stone-700">
            <input type="checkbox" checked={showLastYear} onChange={(e) => setShowLastYear(e.target.checked)} />
            Show last year&apos;s value
          </label>
        </div>
        <p className="mt-0.5 text-xs text-stone-500">
          Pounds per week. Solid line: what was handed out. Dashed green: the forecast, with the shaded
          range from the 10th to the 90th percentile.
        </p>

        {pantries.length === 0 && (
          <p className="mt-4 rounded-md border border-dashed border-stone-300 p-6 text-center text-stone-600">
            There are no pantries yet. Run <code>make seed</code> to load the demo data.
          </p>
        )}
        {loading && (
          <div role="status" aria-live="polite" className="mt-4 h-64 animate-pulse rounded-md bg-stone-100 sm:h-80">
            <span className="sr-only">Loading the chart…</span>
          </div>
        )}
        {error && (
          <div role="alert" className="mt-4 rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-900">
            <p className="font-medium">{error}</p>
            <button
              type="button"
              onClick={() => setRefresh((n) => n + 1)}
              className="mt-2 rounded-md bg-red-700 px-3 py-1.5 font-medium text-white hover:bg-red-800"
            >
              Try again
            </button>
          </div>
        )}
        {series && !error && (
          <>
            {points.length === 0 ? (
              <p className="mt-4 rounded-md border border-dashed border-stone-300 p-6 text-center text-stone-600">
                No history for this pantry and category yet.
              </p>
            ) : (
              <div className="mt-3">
                <ForecastChart
                  points={points}
                  showLastYear={showLastYear}
                  label={`Weekly pounds for ${series.pantry_name}, ${category}: recent history${hasForecast(points) ? " and the forecast" : ""}.`}
                />
                {!hasForecast(points) && (
                  <p className="mt-2 rounded-md border border-dashed border-stone-300 p-3 text-center text-sm text-stone-600">
                    No forecast yet. Click <strong>Run forecast</strong> to predict next week.
                  </p>
                )}
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer font-medium text-green-800">Show the numbers</summary>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="text-stone-500">
                        <tr>
                          <th className="py-1 pr-3 font-medium">Week of</th>
                          <th className="py-1 pr-3 text-right font-medium">Actual</th>
                          <th className="py-1 pr-3 text-right font-medium">Forecast</th>
                          <th className="py-1 pr-3 text-right font-medium">Range</th>
                          <th className="py-1 text-right font-medium">Last year</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-stone-100 tabular-nums">
                        {points.map((p) => (
                          <tr key={p.week_start}>
                            <td className="py-1 pr-3">{weekLabel(p.week_start)}</td>
                            <td className="py-1 pr-3 text-right">{formatPounds(p.actual_lbs)}</td>
                            <td className="py-1 pr-3 text-right">{formatPounds(p.p50_lbs)}</td>
                            <td className="py-1 pr-3 text-right">
                              {p.p10_lbs != null ? `${formatPounds(p.p10_lbs)} to ${formatPounds(p.p90_lbs)}` : "n/a"}
                            </td>
                            <td className="py-1 text-right">{formatPounds(p.baseline_lbs)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="accuracy-heading" className="rounded-lg border border-stone-200 bg-white p-4">
        <h2 id="accuracy-heading" className="text-lg font-semibold">
          How accurate has it been?
        </h2>
        {backtest ? (
          <>
            <p className="mt-0.5 text-sm text-stone-600">
              Error (WAPE, lower is better) over the last 12 weeks, forecasting each week using only what was
              known before it. Run {formatRunTime(backtest.created_at)}, covering weeks from{" "}
              {weekLabel(backtest.backtest_start ?? backtest.horizon_week_start)} to{" "}
              {weekLabel(backtest.backtest_end ?? backtest.train_end)}.
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-stone-200 text-stone-600">
                  <tr>
                    <th className="py-2 pr-4 font-medium" />
                    <th className="py-2 pr-4 text-right font-medium">Forecast model</th>
                    <th className="py-2 text-right font-medium">Last year&apos;s value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100 tabular-nums">
                  <tr>
                    <th scope="row" className="py-2 pr-4 font-normal">
                      All pantries and categories
                    </th>
                    <td className="py-2 pr-4 text-right font-medium">{formatPercent(backtest.wape_lightgbm)}</td>
                    <td className="py-2 text-right">{formatPercent(backtest.wape_baseline)}</td>
                  </tr>
                  <tr>
                    <th scope="row" className="py-2 pr-4 font-normal">
                      {pantry?.name} · {CATEGORY_LABELS[category as keyof typeof CATEGORY_LABELS] ?? category}
                    </th>
                    <td className="py-2 pr-4 text-right font-medium">
                      {loading ? "…" : formatPercent(acc?.wape_lightgbm)}
                    </td>
                    <td className="py-2 text-right">{loading ? "…" : formatPercent(acc?.wape_baseline)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-sm text-stone-700">
              {improvement(backtest.wape_lightgbm, backtest.wape_baseline)} overall. The shaded range held the
              actual amount {formatPercent(backtest.coverage_p10_p90)} of the time (aim: 80%).
            </p>
          </>
        ) : (
          <p className="mt-2 rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-600">
            No accuracy results yet. An administrator can measure it by running <code>make backtest</code>.
          </p>
        )}
      </section>
    </div>
  );
}
