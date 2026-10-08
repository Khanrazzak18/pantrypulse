import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import type { User } from "./api/client";
import { type Role, roleHome } from "./roles";
import { serverFetch } from "./server-api";

/** The logged-in user, or null. Looked up once per request, however many components ask. */
export const getCurrentUser = cache(async (): Promise<User | null> => {
  const res = await serverFetch("/api/auth/me");
  if (res.status === 401) return null;
  if (!res.ok) throw new Error("We could not check your session. Please try again.");
  return (await res.json()) as User;
});

/**
 * Guard for a page. Logged-out visitors go to the login page (and come back here afterwards);
 * users with the wrong role go to their own home. The API enforces the same rules, so this is
 * about showing the right thing, not about security.
 */
export async function requireRole(roles: Role[], here: string): Promise<User> {
  const user = await getCurrentUser();
  if (!user) redirect(`/login?next=${encodeURIComponent(here)}`);
  if (!roles.includes(user.role as Role)) redirect(roleHome(user.role));
  return user;
}
