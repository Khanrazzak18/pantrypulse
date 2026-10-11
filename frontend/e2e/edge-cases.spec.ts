import { expect, file, login, open, staffApi, test } from "./fixtures";

// Requests that real users rarely send but a scanner or a typo will. The server must answer each in
// the error envelope with a 4xx, never a 500. Tests marked test.fail() prove a bug that is recorded in
// docs/testing/bugs.md; Playwright reports them the moment the bug is fixed.

const HUGE = "99999999999999999999";

test.describe("API edge cases", () => {
  test("[API-01][BUG-01] ids larger than the database allows are a 404 or 422, not a 500", async () => {
    test.fail(true, "BUG-01: ids above 2,147,483,647 reach Postgres and come back as 500");
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
      if (res.status() >= 500) bad.push(`${method} ${url} -> ${res.status()}`);
    }
    expect(bad).toEqual([]);
  });

  test("[API-02][BUG-02] a huge pantry_id on the forecast series is a 404 or 422, not a 500", async () => {
    test.fail(true, "BUG-02: pantry_id above the integer range returns 500");
    const api = await staffApi("coordinator");
    const res = await api.get("/api/forecasts/series?pantry_id=99999999999&category=produce");
    expect(res.status()).toBeLessThan(500);
  });

  test("[API-03][BUG-03] a week in year 9999 is not a server error", async () => {
    test.fail(true, "BUG-03: week_start=9999-12-31 returns 500 (the date arithmetic overflows)");
    const api = await staffApi("coordinator");
    for (const week of ["9999-12-31", "0001-01-01"]) {
      const res = await api.get(`/api/allocations?week_start=${week}`);
      expect(res.status(), week).toBeLessThan(500);
    }
  });

  test("[API-04][BUG-04] dashboard dates in year 9999 are not a server error", async () => {
    test.fail(true, "BUG-04: start/end in year 9999 return 500");
    const api = await staffApi("admin");
    for (const range of ["start=9999-01-01&end=9999-12-31", "start=0001-01-01&end=0001-02-01"]) {
      const res = await api.get(`/api/dashboard/metrics?${range}`);
      expect(res.status(), range).toBeLessThan(500);
    }
  });

  test("[API-05][BUG-05] the month 0000-01 is a 404 or 422, not a 500", async () => {
    test.fail(true, "BUG-05: /api/dashboard/summaries/0000-01 returns 500 (year 0 is not a date)");
    const api = await staffApi("admin");
    expect((await api.get("/api/dashboard/summaries/0000-01")).status()).toBeLessThan(500);
    expect((await api.post("/api/dashboard/summaries/0000-01/draft")).status()).toBeLessThan(500);
  });

  test("[API-06][BUG-06] a NUL character in text is a 422, not a 500", async () => {
    test.fail(true, "BUG-06: Postgres cannot store NUL, so notes, summaries and logins containing it return 500");
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
    const serverErrors = Object.entries(results).filter(([, status]) => status >= 500);
    expect(serverErrors).toEqual([]);
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
  test("[SHELL-10][BUG-01] a donation id that is too large shows the not-found page, not an error page", async ({ page }) => {
    test.fail(true, "BUG-01: the API answers 500 for huge ids, so the page shows 'Something went wrong'");
    await login(page, "coordinator");
    await open(page, "/coordinator/donations/9999999999");
    await expect(page.getByRole("heading", { name: /find that/ })).toBeVisible();
  });

  test("[SHELL-13][BUG-08] a missing record answers with HTTP 404, not 200", async ({ page }) => {
    test.fail(true, "BUG-08: pages inside the app shell stream a not-found body with status 200");
    await login(page, "coordinator");
    const res = await page.goto("/coordinator/donations/99999999");
    expect(res?.status()).toBe(404);
  });

  test("[DON-09][BUG-09] every donation can be reached when there are more than 100", async ({ page }) => {
    test.fail(true, "BUG-09: the list is cut at 100 rows with no paging, search or count");
    await login(page, "coordinator");
    const api = await staffApi("coordinator");
    for (let i = 0; i < 3; i++) await api.post("/api/donations", { multipart: { file: file(`n${i}.txt`, "10 cases lettuce") } });
    const total = (await (await api.get("/api/donations?limit=200")).json()).length;
    expect(total).toBeGreaterThan(100);
    await open(page, "/coordinator/donations");
    const shown = await page.getByRole("link", { name: /^(Review|View)$/ }).count();
    const pagingOrNote = await page.getByText(/showing|next page|older|load more|of \d+/i).count();
    expect(shown >= total || pagingOrNote > 0).toBeTruthy();
  });
});
