import type { components } from "./schema";

export type User = components["schemas"]["UserOut"];
export type Pantry = components["schemas"]["PantryOut"];

/** The API's single error shape: {"error": {"code", "message", "details"}}. */
export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
  }
}

export async function errorFromResponse(res: Response): Promise<ApiRequestError> {
  let body: { error?: { code?: string; message?: string; details?: unknown } } | undefined;
  try {
    body = await res.json();
  } catch {
    // not JSON; fall through to the generic message
  }
  const error = body?.error;
  return new ApiRequestError(
    res.status,
    error?.code ?? "unknown_error",
    error?.message ?? "Something went wrong. Please try again.",
    error?.details,
  );
}

/** Browser-side fetch against the same origin (Next.js proxies /api/* to FastAPI). */
export async function apiFetch<T = void>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiRequestError(
      0,
      "network_error",
      "Can't reach the server. Check your connection and try again.",
    );
  }
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
