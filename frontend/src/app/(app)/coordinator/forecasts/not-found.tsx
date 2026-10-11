import { NotFoundPanel } from "@/components/error-panel";

export default function NotFound() {
  return <NotFoundPanel what="that forecast" backHref="/coordinator/forecasts" backLabel="Back to forecasts" />;
}
