"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS, type Role } from "@/lib/roles";

export function NavLinks({ role }: { role: Role }) {
  const pathname = usePathname();
  const items = NAV_ITEMS[role];
  // The most specific link wins, so /coordinator/donations does not also light up "Pantries".
  const matches = items.filter((i) => pathname === i.href || pathname.startsWith(`${i.href}/`));
  const current = matches.sort((a, b) => b.href.length - a.href.length)[0]?.href;
  return (
    <nav aria-label="Main" className="-mx-4 overflow-x-auto px-4">
      <ul className="flex gap-1">
        {items.map((item) => {
          const active = item.href === current;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`block whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${
                  active ? "bg-green-100 text-green-900" : "text-stone-700 hover:bg-stone-100"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
