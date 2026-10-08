import type { components } from "./api/schema";

export type Allocation = components["schemas"]["AllocationOut"];
export type AllocationRun = components["schemas"]["AllocationRunOut"];
export type AllocationList = components["schemas"]["AllocationList"];
export type AllocationSummary = components["schemas"]["AllocationSummary"];

export type StatusFilter = "proposed" | "approved" | "rejected" | "all";

export const STATUS_TABS: { value: StatusFilter; label: string }[] = [
  { value: "proposed", label: "To review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

export type Filters = { status: StatusFilter; county: string; search: string };

export type PantryGroup = {
  pantryId: number;
  name: string;
  county: string;
  miles: number;
  rows: Allocation[];
  totalLbs: number;
};

export function formatLbs(lbs: number): string {
  return `${Math.round(lbs).toLocaleString("en-US")} lb`;
}

/** The amount that will go (or went) out: the final amount once decided, else the proposal. */
export function shownLbs(row: Allocation): number {
  return row.final_lbs ?? row.recommended_lbs;
}

export function matchesFilters(row: Allocation, f: Filters): boolean {
  if (f.status === "approved" ? !["approved", "edited"].includes(row.status) : f.status !== "all" && row.status !== f.status) {
    return false;
  }
  if (f.county && row.pantry.county !== f.county) return false;
  const q = f.search.trim().toLowerCase();
  if (q && !`${row.pantry.name} ${row.lot.item_name} ${row.lot.category}`.toLowerCase().includes(q)) return false;
  return true;
}

export function groupByPantry(rows: Allocation[]): PantryGroup[] {
  const groups = new Map<number, PantryGroup>();
  for (const row of rows) {
    let g = groups.get(row.pantry.id);
    if (!g) {
      g = { pantryId: row.pantry.id, name: row.pantry.name, county: row.pantry.county, miles: row.pantry.miles, rows: [], totalLbs: 0 };
      groups.set(row.pantry.id, g);
    }
    g.rows.push(row);
    g.totalLbs += shownLbs(row);
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** Returns an error message, or null when `text` is a valid amount for a lot with `remaining` lb. */
export function validateEditLbs(text: string, remaining: number): string | null {
  const trimmed = text.trim();
  if (trimmed === "") return "Enter an amount in pounds.";
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return "Enter a number.";
  if (value <= 0) return "Enter more than 0 lb.";
  if (value > remaining + 1e-9) return `That is more than the ${formatLbs(remaining)} left in this lot.`;
  return null;
}

export function expiryLabel(row: Allocation): string {
  const d = row.lot.days_left;
  if (d == null) return "No expiry date";
  if (d <= 0) return "Expires on delivery day";
  return `Expires in ${d} day${d === 1 ? "" : "s"}`;
}

export function statusLabel(status: string): string {
  return { proposed: "To review", approved: "Approved", edited: "Edited", rejected: "Rejected" }[status] ?? status;
}
