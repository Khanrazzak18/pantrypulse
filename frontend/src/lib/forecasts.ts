import type { components } from "./api/schema";

export type ForecastSeries = components["schemas"]["ForecastSeries"];
export type SeriesPoint = components["schemas"]["SeriesPoint"];
export type ForecastRun = components["schemas"]["ForecastRunOut"];
export type LatestRuns = components["schemas"]["LatestRuns"];

export type ChartPoint = {
  weekStart: string;
  label: string;
  actual: number | null;
  p50: number | null;
  p10: number | null;
  p90: number | null;
  band: [number, number] | null;
  lastYear: number | null;
  source: string | null;
};

/** "2026-10-05" as "Oct 5". Done by hand so the server and browser always agree. */
export function weekLabel(iso: string): string {
  const [, month, day] = iso.split("-").map(Number);
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[(month as number) - 1]} ${day}`;
}

export function toChartData(points: SeriesPoint[]): ChartPoint[] {
  return points.map((p) => ({
    weekStart: p.week_start,
    label: weekLabel(p.week_start),
    actual: p.actual_lbs,
    p50: p.p50_lbs,
    p10: p.p10_lbs,
    p90: p.p90_lbs,
    band: p.p10_lbs != null && p.p90_lbs != null ? [p.p10_lbs, p.p90_lbs] : null,
    lastYear: p.baseline_lbs,
    source: p.source,
  }));
}

/** The first week that has a forecast but no actual yet (where the chart changes from past to future). */
export function firstFutureWeek(points: ChartPoint[]): string | null {
  return points.find((p) => p.actual == null && p.p50 != null)?.weekStart ?? null;
}

export function hasForecast(points: SeriesPoint[]): boolean {
  return points.some((p) => p.p50_lbs != null);
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? "n/a" : `${(value * 100).toFixed(1)}%`;
}

export function formatPounds(value: number | null | undefined): string {
  return value == null ? "n/a" : `${Math.round(value).toLocaleString("en-US")} lb`;
}

/** "Oct 8, 2026 at 5:06 PM" in UTC, so the same text renders on the server and in the browser. */
export function formatRunTime(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "UTC" });
  return `${date} at ${time} UTC`;
}

/** Wording for how much better (or worse) the model is than last year's value. */
export function improvement(model: number | null | undefined, baseline: number | null | undefined): string | null {
  if (model == null || baseline == null || baseline === 0) return null;
  const change = (baseline - model) / baseline;
  return `${Math.abs(change * 100).toFixed(0)}% ${change >= 0 ? "lower" : "higher"} error than last year's value`;
}


/** A sentence a screen-reader user can use instead of the picture of the forecast chart. */
export function describeForecast(name: string, category: string, points: SeriesPoint[]): string {
  const actual = [...points].reverse().find((p) => p.actual_lbs != null);
  const next = points.find((p) => p.actual_lbs == null && p.p50_lbs != null);
  const parts = [`${name}, ${category}: ${points.length} weeks shown.`];
  if (actual) parts.push(`The latest actual week (${weekLabel(actual.week_start)}) was ${formatPounds(actual.actual_lbs)}.`);
  if (next) {
    const range = next.p10_lbs != null ? `, likely between ${formatPounds(next.p10_lbs)} and ${formatPounds(next.p90_lbs)}` : "";
    parts.push(`The forecast for next week (${weekLabel(next.week_start)}) is ${formatPounds(next.p50_lbs)}${range}.`);
  } else {
    parts.push("There is no forecast yet.");
  }
  return parts.join(" ");
}
