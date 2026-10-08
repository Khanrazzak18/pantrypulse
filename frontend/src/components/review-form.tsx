"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import {
  ApiRequestError,
  apiFetch,
  type ConfirmRequest,
  type DonationDetail,
  type Donor,
} from "@/lib/api/client";
import {
  CATEGORIES,
  CATEGORY_LABELS,
  isPerishable,
  LOW_CONFIDENCE,
  lowConfidenceFields,
  parseItemField,
  type RowDraft,
  type RowErrors,
  STORAGE_LABELS,
  STORAGE_TYPES,
  toConfirmItem,
  validateRow,
} from "@/lib/donations";

import { StatusBadge } from "./status-badge";

const NEW_DONOR = "__new__";
// Which confidence key belongs to each editable column.
const CONFIDENCE_KEY = {
  name: "name",
  category: "category",
  quantity: "quantity",
  unit: "unit",
  weight: "estimated_weight_lbs",
  expiry: "expiry_date",
  storage: "storage_type",
} as const;
type Column = keyof typeof CONFIDENCE_KEY;
// Server field names mapped onto the columns above.
const SERVER_FIELD: Record<string, keyof RowErrors> = {
  name: "name",
  quantity: "quantity",
  unit: "unit",
  estimated_weight_lbs: "weight",
  expiry_date: "expiry",
};

const utcToday = () => new Date().toISOString().slice(0, 10);
const number = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 1 });

function fromItems(donation: DonationDetail): RowDraft[] {
  return donation.items.map((item, index) => ({
    key: `s${index}`,
    sourceIndex: index,
    name: item.name,
    category: item.category,
    quantity: String(item.quantity),
    unit: item.unit,
    weight: String(item.estimated_weight_lbs),
    expiry: item.expiry_date ?? "",
    storage: item.storage_type,
    confidence: item.confidence,
    edited: new Set<string>(),
  }));
}

function initialDonor(donation: DonationDetail, donors: Donor[]) {
  const suggested = donation.suggested_donor_name?.trim();
  if (!suggested) return { choice: "", newName: "" };
  const match = donors.find((d) => d.name.toLowerCase() === suggested.toLowerCase());
  return match ? { choice: String(match.id), newName: "" } : { choice: NEW_DONOR, newName: suggested };
}

const inputBase =
  "block w-full rounded-md border px-2 py-1.5 text-sm shadow-sm outline-none focus:ring-2 disabled:bg-stone-100";
const inputClass = (invalid: boolean, unsure: boolean) =>
  `${inputBase} ${
    invalid
      ? "border-red-500 focus:ring-red-200"
      : unsure
        ? "border-amber-500 bg-amber-50 focus:ring-amber-200"
        : "border-stone-300 focus:border-green-700 focus:ring-green-200"
  }`;

function Cell({
  label,
  htmlFor,
  error,
  unsure,
  children,
  note,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  unsure?: number;
  children: ReactNode;
  note?: string;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="mb-0.5 block text-xs font-medium text-stone-600 md:sr-only">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${htmlFor}-error`} className="mt-0.5 text-xs text-red-700">
          {error}
        </p>
      )}
      {!error && unsure !== undefined && (
        <p id={`${htmlFor}-unsure`} className="mt-0.5 text-xs font-medium text-amber-800">
          AI unsure ({Math.round(unsure * 100)}%)
        </p>
      )}
      {!error && unsure === undefined && note && <p className="mt-0.5 text-xs text-amber-800">{note}</p>}
    </div>
  );
}

export function ReviewForm({ donation, donors }: { donation: DonationDetail; donors: Donor[] }) {
  const router = useRouter();
  const pending = donation.status === "pending_review";
  const today = utcToday();

  const [rows, setRows] = useState<RowDraft[]>(() => fromItems(donation));
  const [nextKey, setNextKey] = useState(0);
  const [{ choice, newName }, setDonor] = useState(() => initialDonor(donation, donors));
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, RowErrors>>({});
  const [donorServerError, setDonorServerError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState<"confirm" | "reject" | null>(null);
  const [askReject, setAskReject] = useState(false);

  const errorsFor = (row: RowDraft): RowErrors => {
    // Only real server messages override: a cleared one is stored as undefined and must not
    // wipe out the matching client-side error.
    const fromServer = Object.fromEntries(
      Object.entries(serverErrors[row.key] ?? {}).filter(([, message]) => message),
    );
    return { ...(submitted ? validateRow(row, today) : {}), ...fromServer };
  };
  const donorError =
    donorServerError ??
    (submitted && !choice
      ? "Choose a donor, or add a new one."
      : submitted && choice === NEW_DONOR && !newName.trim()
        ? "Enter the donor's name."
        : null);

  const fieldsToCheck = rows.reduce((n, r) => n + lowConfidenceFields(r).length, 0);
  const totalLbs = rows.reduce((n, r) => n + (Number(r.weight) > 0 ? Number(r.weight) : 0), 0);

  function updateRow(key: string, column: Column, value: string) {
    setRows((all) =>
      all.map((r) =>
        r.key !== key
          ? r
          : {
              ...r,
              name: column === "name" ? value : r.name,
              category: column === "category" ? value : r.category,
              quantity: column === "quantity" ? value : r.quantity,
              unit: column === "unit" ? value : r.unit,
              weight: column === "weight" ? value : r.weight,
              expiry: column === "expiry" ? value : r.expiry,
              storage: column === "storage" ? value : r.storage,
              edited: new Set(r.edited).add(CONFIDENCE_KEY[column]),
            },
      ),
    );
    setServerErrors((e) => ({ ...e, [key]: { ...e[key], [column]: undefined } }));
    setBanner(null);
  }

  function addRow() {
    const key = `n${nextKey}`;
    setNextKey((n) => n + 1);
    setRows((all) => [
      ...all,
      {
        key, sourceIndex: null, name: "", category: "produce", quantity: "", unit: "case",
        weight: "", expiry: "", storage: "refrigerated", confidence: {}, edited: new Set(),
      },
    ]);
    setTimeout(() => document.getElementById(`name-${key}`)?.focus(), 0);
  }

  function removeRow(key: string) {
    setRows((all) => all.filter((r) => r.key !== key));
    setBanner(null);
  }

  async function confirm() {
    setSubmitted(true);
    setBanner(null);
    setDonorServerError(null);
    if (rows.length === 0) return setBanner("Add at least one item before confirming.");
    const invalid = rows.some((r) => Object.keys(validateRow(r, today)).length > 0);
    const donorMissing = !choice || (choice === NEW_DONOR && !newName.trim());
    if (invalid || donorMissing) {
      setTimeout(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0);
      return setBanner("Some fields need fixing before this can be confirmed.");
    }
    const body: ConfirmRequest = {
      items: rows.map(toConfirmItem),
      ...(choice === NEW_DONOR ? { donor_name: newName.trim() } : { donor_id: Number(choice) }),
    };
    setBusy("confirm");
    try {
      await apiFetch<DonationDetail>(`/api/donations/${donation.id}/confirm`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      router.push(`/coordinator/donations?added=${rows.length}&lbs=${Math.round(totalLbs)}`);
    } catch (err) {
      setBusy(null);
      showServerError(err);
    }
  }

  function showServerError(err: unknown) {
    if (!(err instanceof ApiRequestError)) return setBanner("Something went wrong. Please try again.");
    if (err.status === 422 && Array.isArray(err.details)) {
      const perRow: Record<string, RowErrors> = {};
      let general: string | null = null;
      for (const d of err.details as { field: string; message: string }[]) {
        const target = parseItemField(d.field);
        const column = target && SERVER_FIELD[target.field];
        const row = target && rows[target.index];
        if (row && column) perRow[row.key] = { ...perRow[row.key], [column]: d.message };
        else if (d.field === "donor_id" || d.field === "donor_name") setDonorServerError(d.message);
        else general = d.message;
      }
      setServerErrors(perRow);
      setBanner(general ?? "Some fields need fixing before this can be confirmed.");
      setTimeout(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0);
    } else {
      setBanner(err.message);
    }
  }

  async function reject() {
    setBusy("reject");
    setBanner(null);
    try {
      await apiFetch<DonationDetail>(`/api/donations/${donation.id}/reject`, { method: "POST" });
      router.push("/coordinator/donations?rejected=1");
    } catch (err) {
      setBusy(null);
      setAskReject(false);
      showServerError(err);
    }
  }

  // ---- read-only view for donations that were already decided --------------------------------
  if (!pending) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-stone-200 bg-white p-4">
          <StatusBadge status={donation.status} />
          <span className="text-sm text-stone-700">
            {donation.status === "confirmed"
              ? `Added to inventory from ${donation.donor_name ?? "an unknown donor"}.`
              : "Rejected. Nothing was added to inventory; the upload is kept on record."}
          </span>
        </div>
        <ul className="space-y-2">
          {donation.items.map((item, i) => (
            <li key={i} className="rounded-lg border border-stone-200 bg-white p-3 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium">{item.name}</span>
                <span className="text-stone-600">
                  {CATEGORY_LABELS[item.category as keyof typeof CATEGORY_LABELS] ?? item.category} ·{" "}
                  {STORAGE_LABELS[item.storage_type as keyof typeof STORAGE_LABELS] ?? item.storage_type}
                </span>
              </div>
              <div className="mt-1 text-stone-700">
                {number(item.quantity)} {item.unit} · {number(item.estimated_weight_lbs)} lb
                {item.expiry_date ? ` · expires ${item.expiry_date}` : ""}
                {item.edited && <span className="ml-2 rounded bg-stone-100 px-1.5 py-0.5 text-xs">edited</span>}
              </div>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // ---- the editable review ---------------------------------------------------------------------
  const busyNow = busy !== null;
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void confirm();
      }}
      aria-busy={busyNow}
      className="space-y-5"
    >
      {banner && (
        <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {banner}{" "}
          {banner.includes("already") && (
            <Link href="/coordinator/donations" className="font-medium underline">
              Back to donations
            </Link>
          )}
        </div>
      )}

      {donation.notes && (
        <div role="note" className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-800">
          <span className="font-medium">Note from the AI:</span> {donation.notes}
        </div>
      )}

      <div className="rounded-lg border border-stone-200 bg-white p-4">
        <label htmlFor="donor" className="block text-sm font-medium">
          Donor
        </label>
        <select
          id="donor"
          value={choice}
          disabled={busyNow}
          onChange={(e) => {
            setDonor({ choice: e.target.value, newName });
            setDonorServerError(null);
          }}
          aria-invalid={Boolean(donorError)}
          aria-describedby={donorError ? "donor-error" : undefined}
          className={`${inputBase} mt-1 max-w-sm ${donorError ? "border-red-500" : "border-stone-300"}`}
        >
          <option value="">Choose a donor…</option>
          {donors.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
          <option value={NEW_DONOR}>New donor…</option>
        </select>
        {choice === NEW_DONOR && (
          <div className="mt-2 max-w-sm">
            <label htmlFor="donor-name" className="sr-only">
              New donor name
            </label>
            <input
              id="donor-name"
              value={newName}
              disabled={busyNow}
              maxLength={120}
              placeholder="Donor name"
              onChange={(e) => {
                setDonor({ choice, newName: e.target.value });
                setDonorServerError(null);
              }}
              aria-invalid={Boolean(donorError)}
              aria-describedby={donorError ? "donor-error" : undefined}
              className={`${inputBase} ${donorError ? "border-red-500" : "border-stone-300"}`}
            />
          </div>
        )}
        {donorError && (
          <p id="donor-error" className="mt-1 text-sm text-red-700">
            {donorError}
          </p>
        )}
        {donation.suggested_donor_name && (
          <p className="mt-1 text-xs text-stone-500">AI read the donor as “{donation.suggested_donor_name}”.</p>
        )}
      </div>

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">
            Items{" "}
            <span className="text-sm font-normal text-stone-600">
              ({rows.length} · {number(totalLbs)} lb)
            </span>
          </h2>
          <p aria-live="polite" className={`text-sm ${fieldsToCheck ? "font-medium text-amber-800" : "text-stone-600"}`}>
            {fieldsToCheck
              ? `${fieldsToCheck} field${fieldsToCheck === 1 ? "" : "s"} the AI was unsure about (highlighted)`
              : `Every field was above ${Math.round(LOW_CONFIDENCE * 100)}% confidence, or you've edited it.`}
          </p>
        </div>

        <div role="table" aria-label="Donation items" className="mt-3 space-y-3">
          <div
            role="row"
            aria-hidden="true"
            className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1.3fr)_2rem] gap-2 px-3 text-xs font-medium uppercase tracking-wide text-stone-500 md:grid"
          >
            <span>Item</span>
            <span>Category</span>
            <span>Qty</span>
            <span>Unit</span>
            <span>Weight (lb)</span>
            <span>Expires</span>
            <span>Storage</span>
            <span />
          </div>

          {rows.length === 0 && (
            <p className="rounded-lg border border-dashed border-stone-300 bg-white p-4 text-center text-sm text-stone-600">
              No items left. Add a row, or reject this donation.
            </p>
          )}

          {rows.map((row, index) => {
            const errors = errorsFor(row);
            const unsure = (column: Column): number | undefined => {
              const key = CONFIDENCE_KEY[column];
              return lowConfidenceFields(row).includes(key) ? row.confidence[key] : undefined;
            };
            const id = (column: string) => `${column}-${row.key}`;
            const describe = (column: Column, hasError: boolean) =>
              hasError ? `${id(column)}-error` : unsure(column) !== undefined ? `${id(column)}-unsure` : undefined;
            return (
              <div
                key={row.key}
                role="row"
                className={`grid grid-cols-2 gap-2 rounded-lg border bg-white p-3 md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1.3fr)_2rem] md:items-start ${
                  row.sourceIndex === null ? "border-green-300" : "border-stone-200"
                }`}
              >
                <div className="col-span-2 md:col-span-1">
                  <Cell label="Item" htmlFor={id("name")} error={errors.name} unsure={unsure("name")}>
                    <input
                      id={id("name")}
                      value={row.name}
                      disabled={busyNow}
                      maxLength={200}
                      onChange={(e) => updateRow(row.key, "name", e.target.value)}
                      aria-invalid={Boolean(errors.name)}
                      aria-describedby={describe("name", Boolean(errors.name))}
                      className={inputClass(Boolean(errors.name), unsure("name") !== undefined)}
                    />
                  </Cell>
                </div>
                <Cell label="Category" htmlFor={id("category")} unsure={unsure("category")}>
                  <select
                    id={id("category")}
                    value={row.category}
                    disabled={busyNow}
                    onChange={(e) => updateRow(row.key, "category", e.target.value)}
                    aria-describedby={describe("category", false)}
                    className={inputClass(false, unsure("category") !== undefined)}
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {CATEGORY_LABELS[c]}
                      </option>
                    ))}
                  </select>
                </Cell>
                <Cell label="Quantity" htmlFor={id("quantity")} error={errors.quantity} unsure={unsure("quantity")}>
                  <input
                    id={id("quantity")}
                    value={row.quantity}
                    inputMode="decimal"
                    disabled={busyNow}
                    onChange={(e) => updateRow(row.key, "quantity", e.target.value)}
                    aria-invalid={Boolean(errors.quantity)}
                    aria-describedby={describe("quantity", Boolean(errors.quantity))}
                    className={inputClass(Boolean(errors.quantity), unsure("quantity") !== undefined)}
                  />
                </Cell>
                <Cell label="Unit" htmlFor={id("unit")} error={errors.unit} unsure={unsure("unit")}>
                  <input
                    id={id("unit")}
                    value={row.unit}
                    disabled={busyNow}
                    maxLength={30}
                    onChange={(e) => updateRow(row.key, "unit", e.target.value)}
                    aria-invalid={Boolean(errors.unit)}
                    aria-describedby={describe("unit", Boolean(errors.unit))}
                    className={inputClass(Boolean(errors.unit), unsure("unit") !== undefined)}
                  />
                </Cell>
                <Cell label="Weight (lb)" htmlFor={id("weight")} error={errors.weight} unsure={unsure("weight")}>
                  <input
                    id={id("weight")}
                    value={row.weight}
                    inputMode="decimal"
                    disabled={busyNow}
                    onChange={(e) => updateRow(row.key, "weight", e.target.value)}
                    aria-invalid={Boolean(errors.weight)}
                    aria-describedby={describe("weight", Boolean(errors.weight))}
                    className={inputClass(Boolean(errors.weight), unsure("weight") !== undefined)}
                  />
                </Cell>
                <Cell
                  label="Expires"
                  htmlFor={id("expiry")}
                  error={errors.expiry}
                  unsure={unsure("expiry")}
                  note={isPerishable(row.category, row.storage) && !row.expiry ? "Fresh food usually needs a date." : undefined}
                >
                  <input
                    id={id("expiry")}
                    type="date"
                    value={row.expiry}
                    disabled={busyNow}
                    onChange={(e) => updateRow(row.key, "expiry", e.target.value)}
                    aria-invalid={Boolean(errors.expiry)}
                    aria-describedby={describe("expiry", Boolean(errors.expiry))}
                    className={inputClass(Boolean(errors.expiry), unsure("expiry") !== undefined)}
                  />
                </Cell>
                <Cell label="Storage" htmlFor={id("storage")} unsure={unsure("storage")}>
                  <select
                    id={id("storage")}
                    value={row.storage}
                    disabled={busyNow}
                    onChange={(e) => updateRow(row.key, "storage", e.target.value)}
                    aria-describedby={describe("storage", false)}
                    className={inputClass(false, unsure("storage") !== undefined)}
                  >
                    {STORAGE_TYPES.map((s) => (
                      <option key={s} value={s}>
                        {STORAGE_LABELS[s]}
                      </option>
                    ))}
                  </select>
                </Cell>
                <div className="col-span-2 flex justify-end md:col-span-1 md:pt-0.5">
                  <button
                    type="button"
                    onClick={() => removeRow(row.key)}
                    disabled={busyNow}
                    aria-label={`Remove row ${index + 1}${row.name ? `: ${row.name}` : ""}`}
                    className="rounded-md border border-stone-300 px-2 py-1 text-sm text-stone-700 hover:bg-red-50 hover:text-red-800 disabled:opacity-50"
                  >
                    <span aria-hidden="true">✕</span>
                    <span className="ml-1 md:sr-only">Remove</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <button
          type="button"
          onClick={addRow}
          disabled={busyNow || rows.length >= 100}
          className="mt-3 rounded-md border border-green-700 bg-white px-3 py-1.5 text-sm font-medium text-green-800 hover:bg-green-50 disabled:opacity-50"
        >
          + Add a row
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-stone-200 pt-4">
        <button
          type="submit"
          disabled={busyNow}
          className="flex items-center gap-2 rounded-md bg-green-700 px-4 py-2 font-medium text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {busy === "confirm" && (
            <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.3" />
              <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
          )}
          {busy === "confirm" ? "Adding to inventory…" : `Confirm and add ${rows.length} lot${rows.length === 1 ? "" : "s"}`}
        </button>

        {!askReject ? (
          <button
            type="button"
            onClick={() => setAskReject(true)}
            disabled={busyNow}
            className="rounded-md border border-stone-300 bg-white px-4 py-2 font-medium text-stone-800 hover:bg-stone-100 disabled:opacity-50"
          >
            Reject
          </button>
        ) : (
          <div role="alertdialog" aria-label="Confirm rejection" className="flex flex-wrap items-center gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm">
            <span className="text-red-900">Reject this donation? Nothing will be added to inventory.</span>
            <button
              type="button"
              onClick={() => void reject()}
              disabled={busyNow}
              className="rounded-md bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800 disabled:opacity-70"
            >
              {busy === "reject" ? "Rejecting…" : "Yes, reject"}
            </button>
            <button
              type="button"
              onClick={() => setAskReject(false)}
              disabled={busyNow}
              className="rounded-md border border-stone-300 bg-white px-3 py-1 font-medium hover:bg-stone-100"
            >
              Keep reviewing
            </button>
          </div>
        )}
      </div>
    </form>
  );
}
