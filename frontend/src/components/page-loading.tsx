export default function PageLoading() {
  return (
    <div role="status" aria-live="polite" className="animate-pulse space-y-3">
      <div className="h-7 w-48 rounded bg-stone-200" />
      <div className="h-4 w-72 rounded bg-stone-200" />
      <div className="h-40 rounded-lg bg-stone-200" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
