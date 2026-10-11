"use client";

import { useEffect, useState } from "react";

/**
 * Two small safety nets for the whole app: a banner while the browser is offline, and a catch for
 * any promise nobody handled, so a failed background request shows a message instead of nothing.
 */
export function ConnectionBanner() {
  const [offline, setOffline] = useState(false);
  const [problem, setProblem] = useState(false);

  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    const onRejection = (event: PromiseRejectionEvent) => {
      if (event.reason instanceof DOMException && event.reason.name === "AbortError") return; // a cancel
      event.preventDefault();
      console.error("Unhandled promise rejection", event.reason);
      setProblem(true);
    };
    const first = setTimeout(update, 0);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      clearTimeout(first);
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  if (!offline && !problem) return null;
  return (
    <div
      role="alert"
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-between gap-3 bg-red-700 px-4 py-2 text-sm text-white"
    >
      <span>
        {offline
          ? "You're offline. Changes can't be saved until your connection is back."
          : "Something went wrong in the background. If a page looks out of date, reload it."}
      </span>
      {!offline && (
        <button type="button" onClick={() => setProblem(false)} className="min-h-11 rounded px-3 font-medium underline">
          Dismiss
        </button>
      )}
    </div>
  );
}
