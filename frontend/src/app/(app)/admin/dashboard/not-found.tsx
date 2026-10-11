import { NotFoundPanel } from "@/components/error-panel";

export default function NotFound() {
  return <NotFoundPanel what="that page" backHref="/admin/dashboard" backLabel="Back to the dashboard" />;
}
