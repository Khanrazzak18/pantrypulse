import type { components } from "./api/schema";
import { CONTROL_MESSAGE, controlCharError } from "./text";

export type Deliveries = components["schemas"]["DeliveriesOut"];
export type Delivery = components["schemas"]["DeliveryOut"];
export type ShortageReport = components["schemas"]["ShortageReportOut"];

export const SEVERITIES = [
  { value: 1, label: "Minor", hint: "Running low" },
  { value: 2, label: "Serious", hint: "Many went without" },
  { value: 3, label: "Ran out", hint: "Nothing left" },
] as const;

export const MAX_TURNED_AWAY = 100000;
export const MAX_NOTE = 500;

export type ReportForm = { category: string; severity: number | null; turnedAway: string; note: string };
export type ReportErrors = Partial<Record<"category" | "severity" | "turnedAway" | "note", string>>;

/** Client-side checks that mirror the server's. An empty object means the form is valid. */
export function validateReport(form: ReportForm): ReportErrors {
  const errors: ReportErrors = {};
  if (!form.category) errors.category = "Choose what ran short.";
  if (form.severity == null) errors.severity = "Choose how bad it was.";
  const t = form.turnedAway.trim();
  if (t !== "") {
    const n = Number(t);
    if (!Number.isInteger(n) || n < 0) errors.turnedAway = "Enter a whole number, 0 or more.";
    else if (n > MAX_TURNED_AWAY) errors.turnedAway = `That is too many (the limit is ${MAX_TURNED_AWAY.toLocaleString("en-US")}).`;
  }
  if (form.note.length > MAX_NOTE) errors.note = `Keep the note under ${MAX_NOTE} characters.`;
  else if (controlCharError(form.note, true)) errors.note = CONTROL_MESSAGE;
  return errors;
}

/** "2026-10-06" as "Tue, Oct 6", done by hand so server and browser always agree. */
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y as number, (m as number) - 1, d as number));
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

/** Days from `from` to `to` (both "YYYY-MM-DD"). */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}
