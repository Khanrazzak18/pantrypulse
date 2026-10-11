import { NotFoundPanel } from "@/components/error-panel";

export default function NotFound() {
  return <NotFoundPanel what="that page" backHref="/pantry" backLabel="Back to my pantry" />;
}
