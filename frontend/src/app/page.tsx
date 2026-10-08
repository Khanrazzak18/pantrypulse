import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { roleHome } from "@/lib/roles";

export default async function Home() {
  const user = await getCurrentUser();
  redirect(user ? roleHome(user.role) : "/login");
}
