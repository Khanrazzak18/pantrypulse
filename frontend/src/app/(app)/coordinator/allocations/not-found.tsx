import { NotFoundPanel } from "@/components/error-panel";

export default function NotFound() {
  return <NotFoundPanel what="that allocation" backHref="/coordinator/allocations" backLabel="Back to allocations" />;
}
