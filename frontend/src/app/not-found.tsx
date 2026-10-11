import { NotFoundPanel } from "@/components/error-panel";

export default function RootNotFound() {
  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <NotFoundPanel what="that page" backHref="/" backLabel="Go to the start page" />
    </main>
  );
}
