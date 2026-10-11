"use client";

import { useRouter } from "next/navigation";
import { startTransition, useEffect } from "react";

import { ErrorPanel } from "./error-panel";

/** The error screen every route segment uses. Pages that cannot load their data end up here. */
export default function SegmentError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const router = useRouter();
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <ErrorPanel
      title="Something went wrong"
      message="We couldn't load this page. Please try again; if it keeps happening, tell an administrator."
      reference={error.digest}
      // a server page that failed must fetch its data again, not just redraw
      onRetry={() => startTransition(() => {
        router.refresh();
        reset();
      })}
    />
  );
}
