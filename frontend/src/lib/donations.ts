import type { components } from "./api/schema";
import { CONTROL_MESSAGE, controlCharError, DATE_RANGE_MESSAGE, dateRangeError } from "./text";

type ConfirmItem = components["schemas"]["ConfirmItem"];

export const CATEGORIES = [
  "produce",
  "dairy",
  "protein",
  "bakery",
  "frozen",
  "canned",
  "dry_goods",
  "beverages",
] as const;
export const STORAGE_TYPES = ["ambient", "refrigerated", "frozen"] as const;

// Compile-time check: these lists must cover everything the API accepts.
type Missing = Exclude<ConfirmItem["category"], (typeof CATEGORIES)[number]> |
  Exclude<ConfirmItem["storage_type"], (typeof STORAGE_TYPES)[number]>;
export const _listsMatchTheApi: [Missing] extends [never] ? true : never = true;

export type Category = (typeof CATEGORIES)[number];
export type StorageType = (typeof STORAGE_TYPES)[number];

export const CATEGORY_LABELS: Record<Category, string> = {
  produce: "Produce",
  dairy: "Dairy",
  protein: "Protein",
  bakery: "Bakery",
  frozen: "Frozen (other)",
  canned: "Canned",
  dry_goods: "Dry goods",
  beverages: "Beverages",
};
export const STORAGE_LABELS: Record<StorageType, string> = {
  ambient: "Ambient",
  refrigerated: "Refrigerated",
  frozen: "Frozen",
};
export const STATUS_LABELS: Record<string, string> = {
  pending_review: "Needs review",
  confirmed: "Confirmed",
  rejected: "Rejected",
};

export const LOW_CONFIDENCE = 0.8;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".eml"];
export const ALLOWED_TYPES_TEXT = "PDF, PNG, JPG, WEBP, TXT or EML";

/** The same checks the server makes, so people hear about a bad file before uploading it. */
export function checkUploadFile(name: string, size: number): string | null {
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : "";
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return `'${name}' can't be used. Upload a ${ALLOWED_TYPES_TEXT} file.`;
  }
  if (size === 0) return `'${name}' is empty.`;
  if (size > MAX_UPLOAD_BYTES) {
    return `This file is ${(size / 1024 / 1024).toFixed(1)} MB. The limit is 10 MB.`;
  }
  return null;
}

/** Fresh food needs an expiry date (frozen food keeps, so it is not flagged). */
export function isPerishable(category: string, storage: string): boolean {
  return ["produce", "dairy", "protein", "bakery"].includes(category) && storage !== "frozen";
}

/** One editable row on the review screen. Numbers are strings while being typed. */
export type RowDraft = {
  key: string;
  sourceIndex: number | null;
  name: string;
  category: string;
  quantity: string;
  unit: string;
  weight: string;
  expiry: string; // YYYY-MM-DD or ""
  storage: string;
  confidence: Record<string, number>;
  edited: Set<string>; // fields the coordinator has touched (their highlight goes away)
};
export type RowErrors = Partial<Record<"name" | "quantity" | "unit" | "weight" | "expiry", string>>;

export function validateRow(row: RowDraft, today: string): RowErrors {
  const errors: RowErrors = {};
  if (!row.name.trim()) errors.name = "Enter the item name.";
  else if (row.name.trim().length > 200) errors.name = "Keep the name under 200 characters.";
  else if (controlCharError(row.name)) errors.name = CONTROL_MESSAGE;
  const quantity = Number(row.quantity);
  if (row.quantity.trim() === "" || !Number.isFinite(quantity) || quantity <= 0) {
    errors.quantity = "Enter a quantity above 0.";
  }
  if (!row.unit.trim()) errors.unit = "Enter a unit.";
  else if (controlCharError(row.unit)) errors.unit = CONTROL_MESSAGE;
  const weight = Number(row.weight);
  if (row.weight.trim() === "" || !Number.isFinite(weight) || weight <= 0) {
    errors.weight = "Enter a weight above 0.";
  } else if (weight > 100_000) errors.weight = "That weight looks too large.";
  if (row.expiry && row.expiry < today) errors.expiry = "This item has already expired.";
  else if (dateRangeError(row.expiry)) errors.expiry = DATE_RANGE_MESSAGE;
  return errors;
}

export function toConfirmItem(row: RowDraft): ConfirmItem {
  return {
    name: row.name.trim(),
    category: row.category as ConfirmItem["category"],
    quantity: Number(row.quantity),
    unit: row.unit.trim(),
    estimated_weight_lbs: Number(row.weight),
    expiry_date: row.expiry || null,
    storage_type: row.storage as ConfirmItem["storage_type"],
    source_index: row.sourceIndex,
  };
}

/** Fields the model was unsure about and the coordinator has not yet touched. */
export function lowConfidenceFields(row: RowDraft): string[] {
  return Object.entries(row.confidence)
    .filter(([field, value]) => value < LOW_CONFIDENCE && !row.edited.has(field))
    .map(([field]) => field);
}

/** Maps a server field path like "items.2.expiry_date" onto a row index and field. */
export function parseItemField(path: string): { index: number; field: string } | null {
  const match = /^items\.(\d+)\.(\w+)$/.exec(path);
  return match ? { index: Number(match[1]), field: match[2] as string } : null;
}
