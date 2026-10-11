import { NotFoundPanel } from "@/components/error-panel";

export default function NotFound() {
  return <NotFoundPanel what="that page" backHref="/coordinator" backLabel="Back to pantries" />;
}
