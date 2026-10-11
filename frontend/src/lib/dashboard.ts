import type { components } from "./api/schema";

export type Metrics = components["schemas"]["MetricsOut"];
export type WeekPoint = components["schemas"]["WeekPoint"];
export type CategoryPoint = components["schemas"]["CategoryPoint"];
export type Summary = components["schemas"]["SummaryOut"];
export type RefreshResult = components["schemas"]["RefreshOut"];

export const PRESETS = [
  { label: "Last 12 weeks", weeks: 12 },
  { label: "Last 26 weeks", weeks: 26 },
  { label: "Last 52 weeks", weeks: 52 },
  { label: "All data", weeks: 0 },
] as const;

export function addWeeks(iso: string, weeks: number): string {
  const d = new Date(Date.parse(iso) + weeks * 7 * 86_400_000);
  return d.toISOString().slice(0, 10);
}

/** The start date of a preset that ends on `dataEnd`; null means "from the first week of data". */
export function presetStart(dataEnd: string, weeks: number): string | null {
  return weeks === 0 ? null : addWeeks(dataEnd, -(weeks - 1));
}

export function formatPct(value: number | null | undefined): string {
  return value == null ? "n/a" : `${value.toFixed(1)}%`;
}

export function formatLb(value: number): string {
  return `${Math.round(value).toLocaleString("en-US")} lb`;
}

export function formatInt(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

/** "2026-09-07" as "Sep 7". */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[(m as number) - 1]} ${d}`;
}

/** The months (YYYY-MM) that have data, newest first, for the summary picker. */
export function monthsBetween(start: string, end: string): string[] {
  const out: string[] = [];
  let [y, m] = start.split("-").map(Number) as [number, number];
  const [ey, em] = end.split("-").map(Number) as [number, number];
  while (y < ey || (y === ey && m <= em)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out.reverse();
}

export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y as number, (m as number) - 1, 1)).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}


/** One sentence a screen-reader user can use instead of the picture of a weekly series. */
export function describeSeries(
  name: string,
  points: { label: string; value: number | null }[],
  format: (n: number) => string,
): string {
  const real = points.filter((p): p is { label: string; value: number } => p.value != null);
  if (real.length === 0) return `${name}: no data in this range.`;
  const lowest = real.reduce((a, b) => (b.value < a.value ? b : a));
  const highest = real.reduce((a, b) => (b.value > a.value ? b : a));
  const latest = real[real.length - 1] as { label: string; value: number };
  return (
    `${name}: ${real.length} week${real.length === 1 ? "" : "s"}, ${real[0]?.label} to ${latest.label}. ` +
    `Lowest ${format(lowest.value)} (week of ${lowest.label}), highest ${format(highest.value)} ` +
    `(week of ${highest.label}), latest ${format(latest.value)}.`
  );
}
