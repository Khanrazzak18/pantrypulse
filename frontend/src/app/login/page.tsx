import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/login-form";
import { getCurrentUser } from "@/lib/auth";
import { roleHome } from "@/lib/roles";
import { safeNext } from "@/lib/safe-next";

export const metadata: Metadata = { title: "Sign in · PantryPulse" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const user = await getCurrentUser();
  if (user) redirect(roleHome(user.role));
  const next = safeNext((await searchParams).next);

  return (
    <main id="main-content" tabIndex={-1} className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-sm flex-col justify-center px-4 py-10">
      <h1 className="text-2xl font-semibold text-green-800">PantryPulse</h1>
      <p className="mt-1 text-stone-600">Sign in to Harvest Bridge Food Bank.</p>
      <div className="mt-6 rounded-lg border border-stone-200 bg-white p-5 shadow-sm">
        <LoginForm next={next} />
      </div>
    </main>
  );
}
