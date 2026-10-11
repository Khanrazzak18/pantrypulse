import type { components } from "./schema";

export type User = components["schemas"]["UserOut"];
export type Pantry = components["schemas"]["PantryOut"];
export type DonationSummary = components["schemas"]["DonationSummary"];
export type DonationDetail = components["schemas"]["DonationDetail"];
export type ReviewItem = components["schemas"]["ReviewItem"];
export type Donor = components["schemas"]["DonorOut"];
export type ConfirmRequest = components["schemas"]["ConfirmRequest"];

/** The API's single error shape: {"error": {"code", "message", "details"}}. */
export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
    readonly requestId?: string | null,
  ) {
    super(message);
  }

  /** True when the API or its database is temporarily away (not a logout, not a bug in the request). */
  get unavailable(): boolean {
    return this.status === 503 || this.code === "service_unavailable";
  }
}

export const DEFAULT_TIMEOUT_MS = 30_000;
export const LONG_TIMEOUT_MS = 120_000; // uploads and AI calls (a manifest can take 95 s with a retry)
export const UNAVAILABLE_MESSAGE = "The service is temporarily unavailable. Please try again in a moment.";
export const OFFLINE_MESSAGE = "You're offline. Check your internet connection and try again.";
export const TIMEOUT_MESSAGE = "This is taking longer than expected. Please try again.";

function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

export async function errorFromResponse(res: Response): Promise<ApiRequestError> {
  let body: { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | undefined;
  try {
    body = await res.json();
  } catch {
    // not JSON; fall through to the generic message
  }
  const error = body?.error;
  return new ApiRequestError(
    res.status,
    error?.code ?? "unknown_error",
    error?.message ?? (res.status === 503 ? UNAVAILABLE_MESSAGE : "Something went wrong. Please try again."),
    error?.details,
    error?.request_id ?? res.headers.get("x-request-id"),
  );
}

/** Run a request with a time limit, turning every way it can fail into an ApiRequestError. */
async function send(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  if (isOffline()) throw new ApiRequestError(0, "offline", OFFLINE_MESSAGE);
  const controller = new AbortController();
  const outer = init.signal;
  if (outer) outer.addEventListener("abort", () => controller.abort(outer.reason), { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  try {
    return await fetch(path, { ...init, signal: controller.signal });
  } catch (err) {
    if (outer?.aborted) throw err; // the caller cancelled on purpose
    if (controller.signal.aborted) throw new ApiRequestError(0, "timeout", TIMEOUT_MESSAGE);
    throw new ApiRequestError(0, isOffline() ? "offline" : "network_error", isOffline() ? OFFLINE_MESSAGE : "Can't reach the server. Check your connection and try again.");
  } finally {
    clearTimeout(timer);
  }
}

/** Browser-side fetch against the same origin (Next.js proxies /api/* to FastAPI). */
export async function apiFetch<T = void>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const res = await send(
    path,
    { ...init, credentials: "same-origin", headers: { "Content-Type": "application/json", ...init.headers } },
    timeoutMs,
  );
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Browser-side multipart upload. The browser sets the Content-Type (with its boundary). */
export async function apiUpload<T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> {
  const res = await send(path, { method: "POST", body: form, credentials: "same-origin", signal }, LONG_TIMEOUT_MS);
  if (!res.ok) throw await errorFromResponse(res);
  return (await res.json()) as T;
}
