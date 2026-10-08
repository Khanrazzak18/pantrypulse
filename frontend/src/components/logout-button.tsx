"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiFetch } from "@/lib/api/client";

export function LogoutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function logout() {
    setBusy(true);
    setFailed(false);
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } catch {
      setBusy(false);
      setFailed(true);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {failed && (
        <span role="alert" className="text-sm text-red-700">
          Couldn&apos;t log out. Try again.
        </span>
      )}
      <button
        type="button"
        onClick={logout}
        disabled={busy}
        className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {busy ? "Logging out…" : "Log out"}
      </button>
    </div>
  );
}
