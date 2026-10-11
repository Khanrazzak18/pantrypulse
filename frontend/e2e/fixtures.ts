import { type APIRequestContext, expect, type Page, request, test as base } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? "8101"}`;
const WEB = `http://127.0.0.1:${process.env.E2E_WEB_PORT ?? "3101"}`;

export type Role = "coordinator" | "admin" | "manager";
export const USERS: Record<Role, { email: string; password: string; home: string }> = {
  coordinator: {
    email: "coordinator@harvestbridge.example.org",
    password: process.env.DEMO_COORDINATOR_PASSWORD ?? "",
    home: "/coordinator",
  },
  admin: {
    email: "admin@harvestbridge.example.org",
    password: process.env.DEMO_ADMIN_PASSWORD ?? "",
    home: "/coordinator",
  },
  manager: {
    email: "manager14@harvestbridge.example.org",
    password: process.env.DEMO_PANTRY_MANAGER_PASSWORD ?? "",
    home: "/pantry",
  },
};

/** Put the test database back to its freshly seeded state (and switch the mock AI on). */
export async function resetData() {
  const res = await fetch(`${API}/__e2e/reset`, { method: "POST" });
  if (!res.ok) throw new Error(`reset failed: ${res.status}`);
}

/** "ok", "down" (every AI call fails) or "bad_numbers" (summaries invent a number). */
export async function setAi(mode: "ok" | "down" | "bad_numbers") {
  const res = await fetch(`${API}/__e2e/llm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error(`setAi failed: ${res.status}`);
}

/** Switch a test-only fault on: db_down, slow, empty_pantries, api_error (or "none"). */
export async function setFault(mode: "none" | "db_down" | "slow" | "empty_pantries" | "api_error") {
  const res = await fetch(`${API}/__e2e/fault`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error(`setFault failed: ${res.status}`);
}

export async function aiCalls(): Promise<string[]> {
  return (await (await fetch(`${API}/__e2e/state`)).json()).llm_calls;
}

/** Sign in without the form: the session cookie lands in the page's browser context. */
export async function login(page: Page, role: Role) {
  const res = await page.request.post("/api/auth/login", {
    data: { email: USERS[role].email, password: USERS[role].password },
  });
  expect(res.ok(), `login as ${role}`).toBeTruthy();
}

/** A separate signed-in API client, for setting up data behind the page's back. */
export async function staffApi(role: Role = "coordinator"): Promise<APIRequestContext> {
  const api = await request.newContext({ baseURL: WEB });
  const res = await api.post("/api/auth/login", {
    data: { email: USERS[role].email, password: USERS[role].password },
  });
  expect(res.ok()).toBeTruthy();
  return api;
}

/** Run the forecast and the allocation so the Allocations page has proposals. */
export async function prepareAllocation(): Promise<APIRequestContext> {
  const api = await staffApi("coordinator");
  expect((await api.post("/api/forecasts/run")).ok()).toBeTruthy();
  expect((await api.post("/api/allocations/run")).ok()).toBeTruthy();
  return api;
}

export async function prepareForecast(): Promise<APIRequestContext> {
  const api = await staffApi("coordinator");
  expect((await api.post("/api/forecasts/run")).ok()).toBeTruthy();
  return api;
}

type Row = { id: number; status: string; pantry: { id: number; name: string; county: string } };

export async function allocationRows(api: APIRequestContext): Promise<Row[]> {
  return (await (await api.get("/api/allocations")).json()).rows;
}

/** Approve the first `count` proposed rows of a pantry (default: the manager's Pantry 14). */
export async function approveFor(api: APIRequestContext, pantryId = 14, count = 3): Promise<number[]> {
  const ids = (await allocationRows(api))
    .filter((r) => r.pantry.id === pantryId && r.status === "proposed")
    .slice(0, count)
    .map((r) => r.id);
  expect(ids.length).toBeGreaterThan(0);
  expect((await api.post("/api/allocations/bulk-approve", { data: { ids } })).ok()).toBeTruthy();
  return ids;
}

/** Fail every matching browser request with a JSON error in the API's envelope. */
export async function failRequests(page: Page, pattern: string | RegExp, status = 500, code = "boom") {
  await page.route(pattern, (route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify({ error: { code, message: "The server could not do that. (test)", details: null } }),
    }),
  );
}

/** Count the requests the page sends to a URL pattern (to prove a double-click sends one). */
export function countRequests(page: Page, method: string, pattern: RegExp): { count: () => number } {
  let n = 0;
  page.on("request", (req) => {
    if (req.method() === method && pattern.test(req.url())) n += 1;
  });
  return { count: () => n };
}

export const test = base.extend<{ fresh: void }>({
  fresh: [
    async ({}, use) => {
      await resetData();
      await use();
    },
    { auto: true },
  ],
});

export { expect };

/** Go to a page and wait until it has finished loading and hydrating, so clicks are not lost. */
export async function open(page: Page, url: string) {
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}

export const isNarrow = (page: Page) => (page.viewportSize()?.width ?? 1280) < 768;
export const isPhoneOrTablet = (page: Page) => (page.viewportSize()?.width ?? 1280) < 1024;

/** A file as Playwright wants it for setInputFiles. */
export const file = (name: string, content: string | Buffer, mimeType = "application/octet-stream") => ({
  name,
  mimeType,
  buffer: Buffer.isBuffer(content) ? content : Buffer.from(content),
});

export const WEIRD = {
  long: "x".repeat(5000),
  emoji: "🥕🍎 Ünïcödé",
  nonLatin: "مرحبا 你好 Привет",
  html: "<script>window.__pwned=1</script><img src=x onerror=\"window.__pwned=1\">",
  sql: "' OR 1=1 --",
  spaces: "     ",
};

/** Add a confirmed lot of fresh produce that expires two days after the E2E server's pinned date. */
export async function addUrgentLot() {
  const res = await fetch(`${API}/__e2e/urgent-lot`, { method: "POST" });
  if (!res.ok) throw new Error(`urgent lot failed: ${res.status}`);
}
