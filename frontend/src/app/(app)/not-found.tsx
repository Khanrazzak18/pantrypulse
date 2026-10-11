import type { Metadata } from "next";

import { NotFoundPanel } from "@/components/error-panel";

export const metadata: Metadata = { title: "Page not found · PantryPulse" };

export default function NotFound() {
  return <NotFoundPanel what="that" />;
}
