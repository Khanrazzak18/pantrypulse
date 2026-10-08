"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { NAV_ITEMS, type Role } from "@/lib/roles";

export function NavLinks({ role }: { role: Role }) {
  const pathname = usePathname();
  const [openAt, setOpenAt] = useState<string | null>(null);
  const items = NAV_ITEMS[role];
  // The menu is open only on the page it was opened on, so choosing a link closes it.
  const open = openAt === pathname;
  // The most specific link wins, so /coordinator/donations does not also light up "Pantries".
  const matches = items.filter((i) => pathname === i.href || pathname.startsWith(`${i.href}/`));
  const current = matches.sort((a, b) => b.href.length - a.href.length)[0];
  const single = items.length === 1;

  const links = (
    <ul className="flex flex-col gap-1 md:flex-row">
      {items.map((item) => {
        const active = item.href === current?.href;
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-h-11 items-center whitespace-nowrap rounded-md px-3 text-sm font-medium lg:min-h-0 lg:py-1.5 ${
                active ? "bg-green-100 text-green-900" : "text-stone-700 hover:bg-stone-100"
              }`}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );

  if (single) return <nav aria-label="Main">{links}</nav>;
  return (
    <nav aria-label="Main">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="main-menu"
        onClick={() => setOpenAt(open ? null : pathname)}
        className="flex min-h-11 w-full items-center justify-between rounded-md border border-stone-300 px-3 text-sm font-medium md:hidden"
      >
        <span>{current?.label ?? "Menu"}</span>
        <span aria-hidden="true">{open ? "▲" : "▼"}</span>
      </button>
      <div id="main-menu" className={`${open ? "mt-2 block" : "hidden"} md:mt-0 md:block`}>
        {links}
      </div>
    </nav>
  );
}
