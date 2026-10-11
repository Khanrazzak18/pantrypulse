import type { Metadata } from "next";
import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { UploadPanel } from "@/components/upload-panel";
import type { DonationSummary } from "@/lib/api/client";
import { requireRole } from "@/lib/auth";
import { STATUS_LABELS } from "@/lib/donations";
import { serverJsonWithHeaders } from "@/lib/server-api";

export const metadata: Metadata = { title: "Donations · PantryPulse" };

const FILTERS = [
  { value: undefined, label: "All" },
  { value: "pending_review", label: "Needs review" },
  { value: "confirmed", label: "Confirmed" },
  { value: "rejected", label: "Rejected" },
] as const;
const SOURCES: Record<string, string> = {
  email: "Email",
  pdf: "PDF",
  image: "Photo",
  text: "Text",
  historical: "Imported",
};

const number = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

const PAGE_SIZE = 50;

type Search = { status?: string; added?: string; lbs?: string; rejected?: string; page?: string };

const linkTo = (status: string | undefined, page: number) => {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (page > 1) query.set("page", String(page));
  const text = query.toString();
  return `/coordinator/donations${text ? `?${text}` : ""}`;
};

export default async function DonationsPage({ searchParams }: { searchParams: Promise<Search> }) {
  await requireRole(["coordinator", "admin"], "/coordinator/donations");
  const params = await searchParams;
  const status = FILTERS.find((f) => f.value === params.status)?.value;
  const requested = Number(params.page);
  const page = Number.isInteger(requested) && requested >= 1 && requested <= 100_000 ? requested : 1;
  const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE) });
  if (status) query.set("status", status);
  const { data: donations, headers } = await serverJsonWithHeaders<DonationSummary[]>(
    `/api/donations?${query}`,
    "/coordinator/donations",
  );
  const total = Number(headers.get("x-total-count")) || donations.length;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const first = donations.length ? (page - 1) * PAGE_SIZE + 1 : 0;
  const last = (page - 1) * PAGE_SIZE + donations.length;

  const added = Number(params.added);
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Donations</h1>
        <p className="mt-1 text-stone-600">Upload a manifest, check what the AI read, and add it to inventory.</p>
      </div>

      {Number.isInteger(added) && added > 0 && (
        <p role="status" className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-900">
          Added {added} lot{added === 1 ? "" : "s"} to inventory ({number(Number(params.lbs) || 0)} lb).
        </p>
      )}
      {params.rejected === "1" && (
        <p role="status" className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-800">
          Donation rejected. Nothing was added to inventory.
        </p>
      )}

      <UploadPanel />

      <nav aria-label="Filter donations" className="-mx-4 overflow-x-auto px-4">
        <ul className="flex gap-1">
          {FILTERS.map((f) => {
            const active = f.value === status;
            return (
              <li key={f.label}>
                <Link
                  href={linkTo(f.value, 1)}
                  aria-current={active ? "page" : undefined}
                  className={`flex min-h-11 items-center whitespace-nowrap rounded-md px-3 text-sm font-medium lg:min-h-0 lg:py-1.5 ${
                    active ? "bg-stone-800 text-white" : "text-stone-700 hover:bg-stone-100"
                  }`}
                >
                  {f.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {donations.length === 0 ? (
        <p className="rounded-lg border border-dashed border-stone-300 bg-white p-8 text-center text-stone-600">
          {status
            ? `No donations with status “${STATUS_LABELS[status]}”.`
            : "No donations yet. Upload a manifest above to get started."}
        </p>
      ) : (
        <>
          <div className="hidden overflow-x-auto rounded-lg border border-stone-200 bg-white md:block" tabIndex={0} role="region" aria-label="Donations table">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Donations, newest first, with donor, items, weight and status</caption>
              <thead className="border-b border-stone-200 bg-stone-50 text-stone-600">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Received</th>
                  <th scope="col" className="px-4 py-2 font-medium">File</th>
                  <th scope="col" className="px-4 py-2 font-medium">Donor</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Items</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Weight (lb)</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="relative px-4 py-2">
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {donations.map((d) => (
                  <tr key={d.id}>
                    <td className="whitespace-nowrap px-4 py-2">{day(d.received_at)}</td>
                    <td className="max-w-56 truncate px-4 py-2" title={d.original_filename ?? ""}>
                      <span className="text-stone-500">{SOURCES[d.source_type] ?? d.source_type} · </span>
                      {d.original_filename ?? "n/a"}
                    </td>
                    <td className="px-4 py-2">
                      {d.donor_name ?? (d.suggested_donor_name ? <span className="text-stone-500">{d.suggested_donor_name} (suggested)</span> : "n/a")}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{d.item_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{number(d.total_lbs)}</td>
                    <td className="px-4 py-2"><StatusBadge status={d.status} /></td>
                    <td className="px-4 py-2 text-right">
                      <Link href={`/coordinator/donations/${d.id}`} className="inline-flex min-h-11 items-center px-2 font-medium text-green-800 hover:underline lg:min-h-0">
                        {d.status === "pending_review" ? "Review" : "View"}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="space-y-3 md:hidden">
            {donations.map((d) => (
              <li key={d.id} className="rounded-lg border border-stone-200 bg-white p-4">
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0 truncate font-medium">{d.original_filename ?? "n/a"}</span>
                  <StatusBadge status={d.status} />
                </div>
                <p className="mt-1 text-sm text-stone-600">
                  {SOURCES[d.source_type] ?? d.source_type} · {day(d.received_at)} ·{" "}
                  {d.donor_name ?? d.suggested_donor_name ?? "donor not set"}
                </p>
                <p className="mt-1 text-sm tabular-nums">
                  {d.item_count} items · {number(d.total_lbs)} lb
                </p>
                <Link href={`/coordinator/donations/${d.id}`} className="mt-1 inline-flex min-h-11 items-center text-sm font-medium text-green-800 hover:underline">
                  {d.status === "pending_review" ? "Review" : "View"}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {total > 0 && (
        <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-3 text-sm text-stone-700">
          <p role="status">
            {donations.length > 0
              ? `Showing ${number(first)}–${number(last)} of ${number(total)}`
              : `No donations on this page (there are ${number(total)}).`}
          </p>
          <div className="flex gap-2">
            {page > 1 && (
              <Link href={linkTo(status, page - 1)} className="inline-flex min-h-11 items-center rounded-md border border-stone-300 bg-white px-4 font-medium hover:bg-stone-50">
                Previous
              </Link>
            )}
            {page < lastPage && (
              <Link href={linkTo(status, page + 1)} className="inline-flex min-h-11 items-center rounded-md border border-stone-300 bg-white px-4 font-medium hover:bg-stone-50">
                Next
              </Link>
            )}
            {donations.length === 0 && page > lastPage && (
              <Link href={linkTo(status, lastPage)} className="inline-flex min-h-11 items-center rounded-md border border-stone-300 bg-white px-4 font-medium hover:bg-stone-50">
                Go to the last page
              </Link>
            )}
          </div>
        </nav>
      )}
    </div>
  );
}
