"use client";

export default function ErrorPage({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-5">
      <h1 className="text-lg font-semibold text-red-900">Something went wrong</h1>
      <p className="mt-1 text-red-800">
        {error.message || "We couldn't load this page."} Please try again.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-3 rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-800"
      >
        Try again
      </button>
    </div>
  );
}
