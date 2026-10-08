export type Role = "coordinator" | "pantry_manager" | "admin";

/** Where each role lands after logging in. Admins can do everything a coordinator can. */
export function roleHome(role: string): string {
  return role === "pantry_manager" ? "/pantry" : "/coordinator";
}

/** The navigation each role sees. Later stages add their pages here. */
export const NAV_ITEMS: Record<Role, { href: string; label: string }[]> = {
  coordinator: [{ href: "/coordinator", label: "Pantries" }],
  admin: [{ href: "/coordinator", label: "Pantries" }],
  pantry_manager: [{ href: "/pantry", label: "My pantry" }],
};

export const ROLE_LABELS: Record<Role, string> = {
  coordinator: "Coordinator",
  admin: "Admin",
  pantry_manager: "Pantry manager",
};
