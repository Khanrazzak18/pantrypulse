"use client";

import { useState } from "react";

import { ApiRequestError, apiFetch } from "@/lib/api/client";
import { CATEGORIES, CATEGORY_LABELS } from "@/lib/donations";
import {
  dayLabel,
  type Deliveries,
  type Delivery,
  daysBetween,
  MAX_NOTE,
  type ReportErrors,
  type ReportForm,
  SEVERITIES,
  type ShortageReport,
  validateReport,
} from "@/lib/pantry";

const field =
  "block w-full rounded-lg border border-stone-300 bg-white px-3 py-3 text-base shadow-sm outline-none focus:border-green-700 focus:ring-2 focus:ring-green-200";
const labelOf = (c: string) => (CATEGORY_LABELS as Record<string, string>)[c] ?? c;

function DeliveryCard({ d }: { d: Delivery }) {
  const left = d.expiry_date ? daysBetween(d.delivery_date, d.expiry_date) : null;
  return (
    <li className="rounded-lg border border-stone-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">{d.item_name}</p>
          <p className="text-sm text-stone-600">{labelOf(d.category)}</p>
        </div>
        <p className="shrink-0 text-lg font-semibold tabular-nums">{Math.round(d.final_lbs).toLocaleString("en-US")} lb</p>
      </div>
      <p className="mt-2 text-sm text-stone-700">
        <span className="font-medium">{dayLabel(d.delivery_date)}</span>
        {d.expiry_date && (
          <span className={left != null && left <= 3 ? " text-red-700" : " text-stone-600"}>
            {" "}
            · use by {dayLabel(d.expiry_date)}
          </span>
        )}
        {d.edited && <span className="text-stone-500"> · amount adjusted by the coordinator</span>}
      </p>
    </li>
  );
}

export function PantryPortal({
  initialDeliveries,
  initialReports,
}: {
  initialDeliveries: Deliveries;
  initialReports: ShortageReport[];
}) {
  const { pantry, upcoming, recent } = initialDeliveries;
  const [reports, setReports] = useState(initialReports);
  const [form, setForm] = useState<ReportForm>({ category: "", severity: null, turnedAway: "", note: "" });
  const [errors, setErrors] = useState<ReportErrors>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const reportOf = (c: string) => reports.find((r) => r.category === c);

  function choose(category: string) {
    const existing = reportOf(category);
    setForm(
      existing
        ? { category, severity: existing.severity, turnedAway: String(existing.households_turned_away || ""), note: existing.note ?? "" }
        : { ...form, category },
    );
    setErrors({});
    setMessage(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = validateReport(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    setMessage(null);
    try {
      const saved = await apiFetch<ShortageReport>("/api/pantry/shortage-reports", {
        method: "POST",
        body: JSON.stringify({
          category: form.category,
          severity: form.severity,
          households_turned_away: form.turnedAway.trim() === "" ? 0 : Number(form.turnedAway),
          note: form.note.trim() || null,
        }),
      });
      setReports((prev) => [...prev.filter((r) => r.category !== saved.category), saved]);
      setMessage({
        kind: "ok",
        text: saved.updated
          ? `Updated your ${labelOf(saved.category).toLowerCase()} report for this week.`
          : `Thank you. Your ${labelOf(saved.category).toLowerCase()} report is saved and will help the next forecast.`,
      });
      setForm({ category: "", severity: null, turnedAway: "", note: "" });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof ApiRequestError || err instanceof Error ? err.message : "Something went wrong." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">{pantry.name}</h1>
        <p className="mt-1 text-stone-600">{pantry.county} County</p>
      </div>

      <section aria-labelledby="incoming">
        <h2 id="incoming" className="text-lg font-semibold">
          Incoming deliveries
        </h2>
        {upcoming.length === 0 ? (
          <p className="mt-2 rounded-lg border border-dashed border-stone-300 p-5 text-center text-stone-600">
            Nothing is scheduled yet. Approved deliveries for your pantry will show up here.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {upcoming.map((d) => (
              <DeliveryCard key={d.id} d={d} />
            ))}
          </ul>
        )}
        {recent.length > 0 && (
          <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium text-stone-700">
              Delivered in the last week ({recent.length})
            </summary>
            <ul className="mt-3 space-y-3">
              {recent.map((d) => (
                <DeliveryCard key={d.id} d={d} />
              ))}
            </ul>
          </details>
        )}
      </section>

      <section aria-labelledby="report">
        <h2 id="report" className="text-lg font-semibold">
          Report a shortage
        </h2>
        <p className="mt-1 text-sm text-stone-600">Tell us what ran short this week. It takes under 30 seconds.</p>
        {message && (
          <p
            role={message.kind === "error" ? "alert" : "status"}
            className={`mt-3 rounded-lg border p-3 text-sm ${message.kind === "ok" ? "border-green-300 bg-green-50 text-green-900" : "border-red-300 bg-red-50 text-red-900"}`}
          >
            {message.text}
          </p>
        )}
        <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-5">
          <fieldset>
            <legend className="mb-2 text-sm font-medium">What ran short?</legend>
            <div className="grid grid-cols-2 gap-2">
              {CATEGORIES.map((c) => {
                const selected = form.category === c;
                const done = reportOf(c);
                return (
                  <button
                    key={c}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => choose(c)}
                    className={`min-h-12 rounded-lg border px-3 py-2 text-left text-sm font-medium ${selected ? "border-green-700 bg-green-50 text-green-900 ring-2 ring-green-200" : "border-stone-300 bg-white"}`}
                  >
                    {labelOf(c)}
                    {done && <span className="block text-xs font-normal text-stone-500">Reported this week</span>}
                  </button>
                );
              })}
            </div>
            {errors.category && <p role="alert" className="mt-1 text-sm text-red-700">{errors.category}</p>}
          </fieldset>

          <fieldset>
            <legend className="mb-2 text-sm font-medium">How bad was it?</legend>
            <div className="grid grid-cols-3 gap-2">
              {SEVERITIES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  aria-pressed={form.severity === s.value}
                  onClick={() => setForm({ ...form, severity: s.value })}
                  className={`min-h-14 rounded-lg border px-2 py-2 text-center text-sm font-medium ${form.severity === s.value ? "border-green-700 bg-green-50 text-green-900 ring-2 ring-green-200" : "border-stone-300 bg-white"}`}
                >
                  {s.label}
                  <span className="block text-xs font-normal text-stone-500">{s.hint}</span>
                </button>
              ))}
            </div>
            {errors.severity && <p role="alert" className="mt-1 text-sm text-red-700">{errors.severity}</p>}
          </fieldset>

          <div>
            <label htmlFor="turned" className="mb-1 block text-sm font-medium">
              Households turned away <span className="font-normal text-stone-500">(optional)</span>
            </label>
            <input id="turned" inputMode="numeric" className={field} value={form.turnedAway} onChange={(e) => setForm({ ...form, turnedAway: e.target.value })} aria-invalid={!!errors.turnedAway} />
            {errors.turnedAway && <p role="alert" className="mt-1 text-sm text-red-700">{errors.turnedAway}</p>}
          </div>

          <div>
            <label htmlFor="note" className="mb-1 block text-sm font-medium">
              Note <span className="font-normal text-stone-500">(optional)</span>
            </label>
            <textarea id="note" rows={2} className={field} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} aria-invalid={!!errors.note} />
            <p className="mt-1 text-xs text-stone-500">{form.note.length}/{MAX_NOTE}</p>
            {errors.note && <p role="alert" className="text-sm text-red-700">{errors.note}</p>}
          </div>

          <button
            type="submit"
            disabled={busy}
            className="min-h-12 w-full rounded-lg bg-green-700 px-4 py-3 text-base font-semibold text-white hover:bg-green-800 disabled:opacity-70"
          >
            {busy ? "Sending…" : form.category && reportOf(form.category) ? "Update report" : "Send report"}
          </button>
        </form>
      </section>
    </div>
  );
}
