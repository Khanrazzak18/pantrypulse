import { STATUS_LABELS } from "@/lib/donations";

const STYLES: Record<string, string> = {
  pending_review: "bg-amber-100 text-amber-900",
  confirmed: "bg-green-100 text-green-900",
  rejected: "bg-stone-200 text-stone-700",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status] ?? "bg-stone-100 text-stone-700"}`}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
