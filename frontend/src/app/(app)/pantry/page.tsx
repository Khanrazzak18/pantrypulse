import type { Metadata } from "next";

import type { Pantry } from "@/lib/api/client";
import { requireRole } from "@/lib/auth";
import { serverJson } from "@/lib/server-api";

export const metadata: Metadata = { title: "My pantry · PantryPulse" };

const number = (n: number) => n.toLocaleString("en-US");

export default async function MyPantryPage() {
  const user = await requireRole(["pantry_manager"], "/pantry");
  const pantry = await serverJson<Pantry>(`/api/pantries/${user.pantry_id}`, "/pantry");

  const facts = [
    ["County", pantry.county],
    ["Households served per month", number(pantry.baseline_households)],
    ["Cold storage", `${number(pantry.cold_capacity_lbs)} lb`],
    ["Dry storage", `${number(pantry.dry_capacity_lbs)} lb`],
  ];

  return (
    <div>
      <h1 className="text-2xl font-semibold">{pantry.name}</h1>
      <p className="mt-1 text-stone-600">Incoming deliveries and shortage reports arrive in a later stage.</p>
      <dl className="mt-6 grid gap-3 sm:grid-cols-2">
        {facts.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-stone-200 bg-white p-4">
            <dt className="text-sm text-stone-500">{label}</dt>
            <dd className="mt-0.5 text-lg font-medium tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
