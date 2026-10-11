import "server-only";

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { errorFromResponse } from "./api/client";

function apiBase(): string {
  const port = process.env.API_PORT;
  if (!port) throw new Error("API_PORT is not set. Run via make (it exports the root .env).");
  return `http://127.0.0.1:${port}`;
}

/** Send a visitor to the "temporarily unavailable" page; Try again there returns to `from`. */
export function serviceUnavailable(from?: string): never {
  redirect(from ? `/unavailable?from=${encodeURIComponent(from)}` : "/unavailable");
}

/** Server-side call to the API, forwarding the visitor's session cookie. Never cached. An API
 * that cannot be reached, or that says it is unavailable (503), sends the visitor to /unavailable. */
export async function serverFetch(path: string, here?: string): Promise<Response> {
  const cookieHeader = (await cookies()).toString();
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      headers: { cookie: cookieHeader },
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
  } catch {
    serviceUnavailable(here);
  }
  if (res.status === 503) serviceUnavailable(here);
  return res;
}

/** GET JSON for a protected page, turning auth failures into the right redirect. */
export async function serverJson<T>(path: string, here: string): Promise<T> {
  return (await serverJsonWithHeaders<T>(path, here)).data;
}

/** Like serverJson, and also returns the response headers (for example X-Total-Count). */
export async function serverJsonWithHeaders<T>(
  path: string,
  here: string,
): Promise<{ data: T; headers: Headers }> {
  const res = await serverFetch(path, here);
  if (res.status === 401) redirect(`/login?next=${encodeURIComponent(here)}`);
  if (res.status === 403) redirect("/");
  if (res.status === 404) notFound();
  if (!res.ok) throw await errorFromResponse(res);
  return { data: (await res.json()) as T, headers: res.headers };
}
