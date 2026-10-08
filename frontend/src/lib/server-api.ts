import "server-only";

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { errorFromResponse } from "./api/client";

function apiBase(): string {
  const port = process.env.API_PORT;
  if (!port) throw new Error("API_PORT is not set. Run via make (it exports the root .env).");
  return `http://127.0.0.1:${port}`;
}

/** Server-side call to the API, forwarding the visitor's session cookie. Never cached. */
export async function serverFetch(path: string): Promise<Response> {
  const cookieHeader = (await cookies()).toString();
  return fetch(`${apiBase()}${path}`, {
    headers: { cookie: cookieHeader },
    cache: "no-store",
  });
}

/** GET JSON for a protected page, turning auth failures into the right redirect. */
export async function serverJson<T>(path: string, here: string): Promise<T> {
  const res = await serverFetch(path);
  if (res.status === 401) redirect(`/login?next=${encodeURIComponent(here)}`);
  if (res.status === 403) redirect("/");
  if (res.status === 404) notFound();
  if (!res.ok) throw await errorFromResponse(res);
  return (await res.json()) as T;
}
