import { expect, file, login, open, staffApi, test, USERS } from "./fixtures";

// Security behaviour in the browser: headers and the Content-Security-Policy on every page (without
// breaking any of them), AI-written text shown as text, a protected-page redirect for every role, and
// sessions that stop working after logout.

const PAGES: [string, "coordinator" | "admin" | "manager" | null][] = [
  ["/login", null],
  ["/coordinator", "coordinator"],
  ["/coordinator/donations", "coordinator"],
  ["/coordinator/forecasts", "coordinator"],
  ["/coordinator/allocations", "coordinator"],
  ["/admin/dashboard", "admin"],
  ["/pantry", "manager"],
  ["/does-not-exist", null],
  ["/unavailable", null],
];

test.describe("headers and CSP", () => {
  // checklist row for the templated title below: "SEC-01"
  for (const [path, role] of PAGES) {
    test(`[SEC-01] ${path} has the security headers and a nonce-based CSP with no violations`, async ({ page }) => {
      const violations: string[] = [];
      page.on("console", (m) => {
        if (/content security policy|refused to (execute|load|apply)/i.test(m.text())) violations.push(m.text());
      });
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (e) =>
          ((window as unknown as { __csp: string[] }).__csp ??= []).push(`${e.violatedDirective} ${e.blockedURI}`),
        );
      });
      if (role) await login(page, role);
      const response = await page.goto(path);
      await page.waitForLoadState("networkidle");
      const h = response!.headers();
      expect(h["x-content-type-options"]).toBe("nosniff");
      expect(h["x-frame-options"]).toBe("DENY");
      expect(h["referrer-policy"]).toBe("no-referrer");
      expect(h["permissions-policy"]).toContain("camera=()");
      expect(h["cross-origin-opener-policy"]).toBe("same-origin");
      expect(h["x-powered-by"]).toBeUndefined();
      expect(h["strict-transport-security"]).toBeUndefined(); // plain http in the tests
      const csp = h["content-security-policy"] ?? "";
      expect(csp).toContain("frame-ancestors 'none'");
      expect(csp).toContain("object-src 'none'");
      expect(csp).toContain("base-uri 'self'");
      expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
      const scriptSrc = csp.split(";").find((d) => d.trim().startsWith("script-src"))!;
      expect(scriptSrc).not.toContain("'unsafe-inline'");
      expect(scriptSrc).not.toContain("'unsafe-eval'"); // the production build
      expect(await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? [])).toEqual([]);
      expect(violations).toEqual([]);
    });
  }

  test("[SEC-02] each page gets a different nonce", async ({ page }) => {
    const seen = new Set<string>();
    for (let i = 0; i < 3; i++) {
      const res = await page.goto("/login");
      seen.add(((res!.headers()["content-security-policy"] ?? "").match(/nonce-([^']+)/) ?? [])[1] ?? "");
    }
    expect(seen.size).toBe(3);
  });

  test("[SEC-03] markup injected into the page without the nonce does not run", async ({ page }) => {
    // What an XSS hole would give an attacker: an inline script and an inline handler in the HTML.
    // They are added to the real response (headers kept), so the browser's own parser enforces the policy.
    await page.route("**/login", async (route) => {
      const response = await route.fetch();
      const body = (await response.text()).replace(
        "</body>",
        '<script>window.__injected = 1</script><img src="x:" onerror="window.__inline = 1"></body>',
      );
      await route.fulfill({ response, body });
    });
    await open(page, "/login");
    await page.waitForTimeout(300);
    const flags = await page.evaluate(() => {
      const w = window as unknown as { __injected?: number; __inline?: number };
      return { injected: w.__injected === 1, inline: w.__inline === 1 };
    });
    expect(flags).toEqual({ injected: false, inline: false });
  });

  test("[SEC-04] the API sends its own headers and no CORS permission", async ({ page }) => {
    const res = await page.request.get("/api/health");
    const h = res.headers();
    expect(h["x-content-type-options"]).toBe("nosniff");
    expect(h["cache-control"]).toBe("no-store");
    expect(h["content-security-policy"]).toContain("default-src 'none'");
    expect(h["access-control-allow-origin"]).toBeUndefined();
  });
});

test.describe("AI-written text", () => {
  test("[SEC-05] hostile text from the model is shown as text and never runs", async ({ page }) => {
    await login(page, "coordinator");
    const api = await staffApi("coordinator");
    const res = await api.post("/api/donations", { multipart: { file: file("x.txt", "E2E_XSS 1 case lettuce") } });
    const id = (await res.json()).id;
    await open(page, `/coordinator/donations/${id}`);
    await expect(page.getByText("<script>window.__pwned=1</script><b>bold?</b>")).toBeVisible();
    await expect(page.getByText(/AI read the donor as/)).toContainText("<img src=x onerror=window.__pwned=1>");
    await expect(page.locator("main b")).toHaveCount(0); // not turned into real bold text
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
    await open(page, "/coordinator/donations");
    await expect(page.locator("main script")).toHaveCount(0);
  });
});

test.describe("sessions", () => {
  test("[SEC-06] a copied session cookie stops working once the user logs out", async ({ page, context }) => {
    await login(page, "coordinator");
    const copied = (await context.cookies()).find((c) => c.name === "pp_session")!;
    expect((await page.request.get("/api/auth/me")).status()).toBe(200);
    await open(page, "/coordinator");
    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await context.addCookies([copied]);
    expect((await page.request.get("/api/auth/me")).status()).toBe(401);
    await page.goto("/coordinator");
    await expect(page).toHaveURL(/\/login/);
  });

  test("[SEC-07] logging out on one device logs out the others", async ({ browser }) => {
    const a = await browser.newContext();
    const b = await browser.newContext();
    const base = process.env.E2E_WEB_PORT ?? "3101";
    const creds = { email: USERS.admin.email, password: USERS.admin.password };
    await a.request.post(`http://127.0.0.1:${base}/api/auth/login`, { data: creds });
    await b.request.post(`http://127.0.0.1:${base}/api/auth/login`, { data: creds });
    expect((await b.request.get(`http://127.0.0.1:${base}/api/auth/me`)).status()).toBe(200);
    await a.request.post(`http://127.0.0.1:${base}/api/auth/logout`);
    expect((await b.request.get(`http://127.0.0.1:${base}/api/auth/me`)).status()).toBe(401);
    await a.close();
    await b.close();
  });

  test("[SEC-08] every protected page redirects a logged-out visitor, /admin included", async ({ page }) => {
    for (const path of ["/coordinator", "/coordinator/donations", "/coordinator/forecasts", "/coordinator/allocations", "/pantry", "/admin/dashboard", "/admin/anything"]) {
      const res = await page.goto(path, { waitUntil: "commit" });
      await expect(page, path).toHaveURL(/\/login\?next=/);
      expect(res?.status()).toBe(200); // the redirect has already been followed to the login page
    }
  });
});

test.describe("cross-site requests", () => {
  test("[SEC-09] a request that changes data and claims to come from another site is refused", async ({ page }) => {
    await login(page, "coordinator");
    const res = await page.request.post("/api/allocations/bulk-approve", {
      data: { ids: [1] },
      headers: { Origin: "https://evil.example" },
    });
    expect(res.status()).toBe(403);
    expect((await res.json()).error.code).toBe("forbidden_origin");
  });

  test("[SEC-10] the page's own requests are not blocked by the Origin check", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/forecasts");
    await page.getByRole("button", { name: /Run forecast/ }).click();
    await expect(page.getByText(/saved in/)).toBeVisible({ timeout: 30_000 });
  });
});
