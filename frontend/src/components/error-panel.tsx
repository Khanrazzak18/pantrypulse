"use client";

import Link from "next/link";

/** The one look for "something went wrong" and "not found" screens, so every segment matches. */
export function ErrorPanel({
  title,
  message,
  onRetry,
  retryLabel = "Try again",
  home = true,
  reference,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  home?: boolean;
  reference?: string | null;
}) {
  return (
    <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-5">
      <h1 className="text-lg font-semibold text-red-900">{title}</h1>
      <p className="mt-1 text-red-800">{message}</p>
      {reference && <p className="mt-1 text-xs text-red-700">Reference: {reference}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-md bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-800"
          >
            {retryLabel}
          </button>
        )}
        {home && (
          <Link
            href="/"
            className="inline-flex min-h-11 items-center rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-900 hover:bg-red-100"
          >
            Go to your home page
          </Link>
        )}
      </div>
    </div>
  );
}

export function NotFoundPanel({ what = "that", backHref = "/", backLabel = "Go to your home page" }: { what?: string; backHref?: string; backLabel?: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-6">
      <h1 className="text-xl font-semibold">We couldn&apos;t find {what}</h1>
      <p className="mt-1 text-stone-600">It may have been removed, or the link is wrong.</p>
      <Link href={backHref} className="mt-3 inline-flex min-h-11 items-center font-medium text-green-800 hover:underline">
        {backLabel}
      </Link>
    </div>
  );
}
