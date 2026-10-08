import { AppShell } from "@/components/app-shell";
import { getCurrentUser } from "@/lib/auth";

// Pages guard themselves (and remember where the visitor was going). If nobody is logged in the
// page redirects to /login, so the shell is simply skipped here.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) return <>{children}</>;
  return <AppShell user={user}>{children}</AppShell>;
}
