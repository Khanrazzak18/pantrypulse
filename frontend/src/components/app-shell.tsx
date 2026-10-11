import type { User } from "@/lib/api/client";
import { ROLE_LABELS, type Role } from "@/lib/roles";

import { LogoutButton } from "./logout-button";
import { NavLinks } from "./nav-links";

export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const role = user.role as Role;
  return (
    <div className="min-h-[calc(100vh-5rem)]">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto max-w-5xl space-y-2 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-lg font-semibold text-green-800">PantryPulse</span>
            <div className="flex items-center gap-3">
              <div className="hidden text-right text-sm leading-tight sm:block">
                <div className="font-medium">{user.full_name}</div>
                <div className="text-stone-600">
                  {ROLE_LABELS[role]}
                  {user.pantry_name ? ` · ${user.pantry_name}` : ""}
                </div>
              </div>
              <LogoutButton />
            </div>
          </div>
          <NavLinks role={role} />
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className="mx-auto max-w-5xl px-4 py-6">
        {children}
      </main>
    </div>
  );
}
