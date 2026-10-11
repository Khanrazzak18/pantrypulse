"use client";

import { useEffect } from "react";

/** Sets the tab title from a client component (error screens), where `metadata` is not available. */
export function PageTitle({ title }: { title: string }) {
  useEffect(() => {
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
  return null;
}
