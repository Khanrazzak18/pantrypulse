import { open, expect, login, countRequests, test, USERS, WEIRD } from "./fixtures";

const form = (page: import("@playwright/test").Page) => ({
  email: page.getByLabel("Email"),
  password: page.getByLabel("Password"),
  submit: page.getByRole("button", { name: "Sign in" }),
});

test.describe("logged out", () => {
  test("[ANON-01] the root URL goes to the login page", async ({ page }) => {
    await open(page, "/");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("[ANON-02] protected coordinator pages redirect to login with next", async ({ page }) => {
    for (const path of ["/coordinator", "/coordinator/donations", "/coordinator/forecasts", "/coordinator/allocations"]) {
      await open(page, `${path}?x=1`);
      await expect(page).toHaveURL(new RegExp(`/login\\?next=${encodeURIComponent(path + "?x=1").replace(/[?]/g, "\\?")}`));
    }
  });

  test("[ANON-03] /pantry redirects to login", async ({ page }) => {
    await open(page, "/pantry");
    await expect(page).toHaveURL(/\/login\?next=%2Fpantry/);
  });

  test("[ANON-04] /admin/dashboard redirects to login", async ({ page }) => {
    await open(page, "/admin/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Fdashboard/);
  });

  test("[ANON-05] an unknown URL shows a readable not-found page", async ({ page }) => {
    const res = await page.goto("/does-not-exist");
    expect(res?.status()).toBe(404);
    await expect(page.getByText(/could not be found|not found/i).first()).toBeVisible();
    const long = await page.goto(`/${"a".repeat(2000)}/${encodeURIComponent("🥕")}`);
    expect(long?.status()).toBe(404);
  });

  test("[ANON-08] a garbage session cookie sends the visitor to login", async ({ page, context }) => {
    await context.addCookies([{ name: "pp_session", value: "garbage", url: page.url() === "about:blank" ? "http://127.0.0.1:3101" : page.url() }]);
    await open(page, "/coordinator");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("sign in", () => {
  for (const [id, role] of [["LOGIN-01", "coordinator"], ["LOGIN-02", "admin"], ["LOGIN-03", "manager"]] as const) {
    test(`[${id}] ${role} signs in and lands on their home`, async ({ page }) => {
      await open(page, "/login");
      const f = form(page);
      await f.email.fill(USERS[role].email);
      await f.password.fill(USERS[role].password);
      await f.submit.click();
      await expect(page).toHaveURL(new RegExp(`${USERS[role].home}$`));
    });
  }

  test("[LOGIN-04] a safe next parameter is honoured", async ({ page }) => {
    await open(page, "/login?next=/coordinator/forecasts");
    const f = form(page);
    await f.email.fill(USERS.coordinator.email);
    await f.password.fill(USERS.coordinator.password);
    await f.submit.click();
    await expect(page).toHaveURL(/\/coordinator\/forecasts$/);
  });

  test("[LOGIN-05] unsafe next parameters are ignored", async ({ page }) => {
    for (const next of ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)"]) {
      await open(page, `/login?next=${encodeURIComponent(next)}`);
      const f = form(page);
      await f.email.fill(USERS.coordinator.email);
      await f.password.fill(USERS.coordinator.password);
      await f.submit.click();
      await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/coordinator$/);
      await page.context().clearCookies();
    }
  });

  test("[LOGIN-06] an empty form shows inline messages and sends nothing", async ({ page }) => {
    await open(page, "/login");
    const sent = countRequests(page, "POST", /\/api\/auth\/login/);
    await form(page).submit.click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    await expect(page.getByText("Enter your password.")).toBeVisible();
    expect(sent.count()).toBe(0);
  });

  test("[LOGIN-07] spaces only is treated as empty", async ({ page }) => {
    await open(page, "/login");
    const sent = countRequests(page, "POST", /\/api\/auth\/login/);
    const f = form(page);
    await f.email.fill(WEIRD.spaces);
    await f.password.fill(WEIRD.spaces);
    await f.submit.click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    expect(sent.count()).toBe(0);
  });

  test("[LOGIN-08] a badly formed email is explained", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    for (const bad of ["not-an-email", "a@b", "@b.co", "a b@c.de"]) {
      await f.email.fill(bad);
      await f.password.fill("whatever");
      await f.submit.click();
      await expect(page.getByText("Enter a valid email address.")).toBeVisible();
    }
  });

  test("[LOGIN-09][LOGIN-10] wrong password and unknown email give the same message", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    await f.email.fill(USERS.coordinator.email);
    await f.password.fill("definitely-wrong");
    await f.submit.click();
    const first = page.getByRole("alert").filter({ hasText: /incorrect/i });
    await expect(first).toBeVisible();
    const message = await first.innerText();
    await expect(f.password).toBeFocused();
    await f.email.fill("nobody@example.org");
    await f.submit.click();
    await expect(page.getByRole("alert").filter({ hasText: /incorrect/i })).toHaveText(message);
  });

  test("[LOGIN-11] five wrong passwords lock the email, even for the right password", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    for (let i = 0; i < 5; i++) {
      await f.email.fill(USERS.coordinator.email);
      await f.password.fill(`wrong-${i}`);
      await f.submit.click();
      await expect(page.getByRole("alert").filter({ hasText: /incorrect/i })).toBeVisible();
    }
    await f.password.fill(USERS.coordinator.password);
    await f.submit.click();
    await expect(page.getByRole("alert").filter({ hasText: /too many failed attempts/i })).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("[LOGIN-12] 5,000 characters in the fields are capped or refused", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    await f.email.fill(WEIRD.long);
    await f.password.fill(WEIRD.long);
    expect((await f.email.inputValue()).length).toBeLessThanOrEqual(254);
    expect((await f.password.inputValue()).length).toBeLessThanOrEqual(200);
    await f.submit.click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("[LOGIN-13] emoji and non-Latin text are an ordinary wrong login", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    await f.email.fill("🥕@例え.jp");
    await f.password.fill(WEIRD.nonLatin + WEIRD.emoji);
    await f.submit.click();
    await expect(page.getByText(/valid email|incorrect/i).first()).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("[LOGIN-14] HTML and SQL text are just wrong input", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    await f.email.fill("a'OR1=1--@b.co");
    await f.password.fill(WEIRD.html);
    await f.submit.click();
    await expect(page.getByRole("alert").filter({ hasText: /incorrect/i })).toBeVisible();
    await f.email.fill(WEIRD.html);
    await f.submit.click();
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
    await expect(page).toHaveURL(/\/login/);
  });

  test("[LOGIN-15] double-clicking Sign in sends one request", async ({ page }) => {
    await open(page, "/login");
    const sent = countRequests(page, "POST", /\/api\/auth\/login/);
    const f = form(page);
    await f.email.fill(USERS.coordinator.email);
    await f.password.fill(USERS.coordinator.password);
    await f.submit.dblclick();
    await expect(page).toHaveURL(/\/coordinator$/);
    expect(sent.count()).toBe(1);
  });

  test("[LOGIN-16] the Enter key submits", async ({ page }) => {
    await open(page, "/login");
    const f = form(page);
    await f.email.fill(USERS.admin.email);
    await f.password.fill(USERS.admin.password);
    await f.password.press("Enter");
    await expect(page).toHaveURL(/\/coordinator$/);
  });

  test("[LOGIN-17] the password field is masked", async ({ page }) => {
    await open(page, "/login");
    await expect(form(page).password).toHaveAttribute("type", "password");
  });

  test("[LOGIN-18] a signed-in user opening /login is sent home", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/login");
    await expect(page).toHaveURL(/\/coordinator$/);
  });

  test("[ANON-07] the back button after logging out shows no private data", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator");
    await expect(page.getByRole("heading", { name: "Pantries" })).toBeVisible();
    await open(page, "/coordinator/donations");
    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goBack();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: "Donations" })).toHaveCount(0);
    await expect(page).toHaveURL(/\/login/);
  });
});
