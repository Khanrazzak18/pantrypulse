import { NotFoundPanel } from "@/components/error-panel";

export default function NotFound() {
  return <NotFoundPanel what="that donation" backHref="/coordinator/donations" backLabel="Back to donations" />;
}
