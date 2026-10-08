"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS, type Role } from "@/lib/roles";

export function NavLinks({ role }: { role: Role }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="-mx-4 overflow-x-auto px-4">
      <ul className="flex gap-1">
        {NAV_ITEMS[role].map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
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
