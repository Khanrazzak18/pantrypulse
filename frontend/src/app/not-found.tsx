import type { Metadata } from "next";

import { NotFoundPanel } from "@/components/error-panel";

export const metadata: Metadata = { title: "Page not found · PantryPulse" };

export default function RootNotFound() {
  return (
    <main id="main-content" tabIndex={-1} className="mx-auto max-w-xl px-4 py-12">
      <NotFoundPanel what="that page" backHref="/" backLabel="Go to the start page" />
    </main>
  );
}
