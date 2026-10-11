import { expect, file, login, open, staffApi, test } from "./fixtures";

// Requests that real users rarely send but a scanner or a typo will. The server must answer each in
// the error envelope with a 4xx, never a 500. Each test guards a bug recorded in docs/testing/bugs.md.

const HUGE = "99999999999999999999";

test.describe("API edge cases", () => {
  test("[API-01] ids larger than the database allows are a 404 in the envelope", async () => {
    const api = await staffApi("admin");
    const calls: [string, string][] = [
      ["GET", `/api/donations/${HUGE}`],
      ["GET", "/api/donations/9999999999"],
      ["GET", "/api/pantries/9999999999"],
      ["POST", `/api/allocations/${HUGE}/approve`],
      ["POST", "/api/allocations/99999999999/reject"],
      ["POST", "/api/allocations/runs/99999999999/reasons"],
    ];
    const bad: string[] = [];
    for (const [method, url] of calls) {
      const res = await api.fetch(url, { method });
      if (res.status() !== 404) bad.push(`${method} ${url} -> ${res.status()}`);
    }
    expect(bad).toEqual([]);
  });

  test("[API-02] a huge pantry_id on the forecast series is a 404 or 422, not a 500", async () => {
    const api = await staffApi("coordinator");
    const res = await api.get("/api/forecasts/series?pantry_id=99999999999&category=produce");
    expect(res.status()).toBe(422);
  });

  test("[API-03] a week in year 9999 is not a server error", async () => {
    const api = await staffApi("coordinator");
    for (const week of ["9999-12-31", "0001-01-01"]) {
      const res = await api.get(`/api/allocations?week_start=${week}`);
      expect(res.status(), week).toBe(422);
      expect(JSON.stringify(await res.json())).toContain("between 2020 and 2100");
    }
  });

  test("[API-04] dashboard dates in year 9999 are not a server error", async () => {
    const api = await staffApi("admin");
    for (const range of ["start=9999-01-01&end=9999-12-31", "start=0001-01-01&end=0001-02-01"]) {
      const res = await api.get(`/api/dashboard/metrics?${range}`);
      expect(res.status(), range).toBe(422);
    }
  });

  test("[API-05] the month 0000-01 is a 404 or 422, not a 500", async () => {
    const api = await staffApi("admin");
    expect((await api.get("/api/dashboard/summaries/0000-01")).status()).toBe(422);
    expect((await api.post("/api/dashboard/summaries/0000-01/draft")).status()).toBe(422);
  });

  test("[API-06] a NUL character in text is a 422, not a 500", async () => {
    const nul = "a\u0000b";
    const admin = await staffApi("admin");
    const manager = await staffApi("manager");
    const anon = await staffApi("coordinator");
    const results: Record<string, number> = {};
    results.shortageNote = (await manager.post("/api/pantry/shortage-reports", { data: { category: "dairy", severity: 1, note: nul } })).status();
    results.summary = (await admin.post("/api/dashboard/summaries/2026-09/approve", { data: { text: nul } })).status();
    await admin.post("/api/forecasts/run");
    await admin.post("/api/allocations/run");
    const first = (await (await admin.get("/api/allocations")).json()).rows[0].id;
    results.editNote = (await admin.post(`/api/allocations/${first}/edit`, { data: { lbs: 5, note: nul } })).status();
    results.loginEmail = (await anon.post("/api/auth/login", { data: { email: `${nul}@x.co`, password: "x" } })).status();
    expect(Object.entries(results).filter(([, status]) => status !== 422)).toEqual([]);
  });

  test("[API-07] SQL and HTML text in query parameters is a 422 or an empty result", async () => {
    const api = await staffApi("admin");
    const evil = encodeURIComponent("' OR 1=1 --");
    const html = encodeURIComponent("<script>alert(1)</script>");
    for (const url of [
      `/api/donations?status=${evil}`,
      `/api/forecasts?category=${evil}`,
      `/api/forecasts?category=${html}`,
      `/api/allocations?status=${html}`,
      `/api/allocations?week_start=${evil}`,
      `/api/dashboard/metrics?start=${evil}`,
      `/api/dashboard/summaries/${evil}`,
    ]) {
      const res = await api.get(url);
      expect(res.status(), url).toBeLessThan(500);
      expect(res.headers()["content-type"]).toContain("application/json");
    }
  });
});

test.describe("page edge cases", () => {
  test("[SHELL-10] a donation id that is too large shows the not-found page, not an error page", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/donations/9999999999");
    await expect(page.getByRole("heading", { name: /find that/ })).toBeVisible();
  });

  test("[SHELL-13] a missing record answers with a real HTTP 404", async ({ page }) => {
    await login(page, "coordinator");
    const res = await page.goto("/coordinator/donations/99999999");
    expect(res?.status()).toBe(404);
  });

  test("[DON-09][DON-10] every donation can be reached: Showing X–Y of Z with Next and Previous", async ({ page }) => {
    await login(page, "coordinator");
    const api = await staffApi("coordinator");
    for (let i = 0; i < 3; i++) await api.post("/api/donations", { multipart: { file: file(`n${i}.txt`, "10 cases lettuce") } });
    const total = Number((await api.get("/api/donations?limit=1")).headers()["x-total-count"]);
    expect(total).toBeGreaterThan(100);
    await open(page, "/coordinator/donations");
    await expect(page.getByText(`Showing 1–50 of ${total.toLocaleString("en-US")}`)).toBeVisible();
    await page.getByRole("link", { name: "Next", exact: true }).click();
    await expect(page).toHaveURL(/page=2/);
    await expect(page.getByText(`Showing 51–100 of ${total.toLocaleString("en-US")}`)).toBeVisible();
    await page.getByRole("link", { name: "Previous", exact: true }).click();
    await expect(page.getByText(/Showing 1–50/)).toBeVisible();
    const lastPage = Math.ceil(total / 50);
    await open(page, `/coordinator/donations?page=${lastPage}`);
    await expect(page.getByRole("link", { name: "Next", exact: true })).toHaveCount(0);
    await expect(page.getByText(new RegExp(`Showing ${((lastPage - 1) * 50 + 1).toLocaleString("en-US")}–${total.toLocaleString("en-US")} of`))).toBeVisible();
  });

  test("[DON-11] odd page numbers in the URL give a sensible page", async ({ page }) => {
    await login(page, "coordinator");
    for (const q of ["abc", "0", "-3", "1.5", "99999999", encodeURIComponent("<script>")]) {
      await open(page, `/coordinator/donations?page=${q}`);
      await expect(page.getByRole("heading", { name: "Donations" })).toBeVisible();
      await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
    }
    await open(page, "/coordinator/donations?page=5000");
    await expect(page.getByRole("link", { name: "Go to the last page" })).toBeVisible();
  });
});
