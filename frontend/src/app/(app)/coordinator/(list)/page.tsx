import type { Metadata } from "next";

import type { Pantry } from "@/lib/api/client";
import { requireRole } from "@/lib/auth";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "Pantries · PantryPulse" };

const number = (n: number) => n.toLocaleString("en-US");

export default async function PantriesPage() {
  await requireRole(["coordinator", "admin"], "/coordinator");
  const pantries = await serverJson<Pantry[]>("/api/pantries", "/coordinator");

  return (
    <div>
      <h1 className="text-2xl font-semibold">Pantries</h1>
      <p className="mt-1 text-stone-600">
        {pantries.length} partner pantries across{" "}
        {new Set(pantries.map((p) => p.county)).size} counties.
      </p>

      {pantries.length === 0 ? (
        <p className="mt-6 rounded-lg border border-dashed border-stone-300 bg-white p-6 text-center text-stone-600">
          No pantries yet. Run <code>make seed</code> to load the demo data.
        </p>
      ) : (
        <>
          <div className="mt-6 hidden overflow-x-auto rounded-lg border border-stone-200 bg-white md:block" tabIndex={0} role="region" aria-label="Partner pantries table">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Partner pantries with county, households per month and storage capacity</caption>
              <thead className="border-b border-stone-200 bg-stone-50 text-stone-600">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Pantry</th>
                  <th scope="col" className="px-4 py-2 font-medium">County</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Households / month</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Cold storage (lb)</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Dry storage (lb)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {pantries.map((p) => (
                  <tr key={p.id}>
                    <th scope="row" className="px-4 py-2 font-medium">{p.name}</th>
                    <td className="px-4 py-2">{p.county}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{number(p.baseline_households)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{number(p.cold_capacity_lbs)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{number(p.dry_capacity_lbs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="mt-6 space-y-3 md:hidden">
            {pantries.map((p) => (
              <li key={p.id} className="rounded-lg border border-stone-200 bg-white p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{p.name}</span>
                  <span className="text-sm text-stone-600">{p.county}</span>
                </div>
                <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
                  <div>
                    <dt className="text-stone-500">Households</dt>
                    <dd className="tabular-nums">{number(p.baseline_households)}</dd>
                  </div>
                  <div>
                    <dt className="text-stone-500">Cold (lb)</dt>
                    <dd className="tabular-nums">{number(p.cold_capacity_lbs)}</dd>
                  </div>
                  <div>
                    <dt className="text-stone-500">Dry (lb)</dt>
                    <dd className="tabular-nums">{number(p.dry_capacity_lbs)}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
