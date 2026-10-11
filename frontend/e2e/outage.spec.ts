import { expect, login, open, setFault, test } from "./fixtures";

// States that are hard to reach with real data, switched on through the test server's fault modes:
// the database is down, the API is slow, the pantry list is empty, or a page's data request fails.

test.describe("outages", () => {
  test("[OUT-01][OUT-02] a database outage shows a temporary-unavailable page, and Try again recovers", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/forecasts");
    await setFault("db_down");
    await page.goto("/coordinator/forecasts");
    await expect(page.getByRole("heading", { name: /temporarily unavailable/ })).toBeVisible();
    await expect(page).toHaveURL(/\/unavailable\?from=%2Fcoordinator%2Fforecasts/);
    await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    await setFault("none");
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page).toHaveURL(/\/coordinator\/forecasts$/);
    await expect(page.getByRole("heading", { name: "Forecasts" })).toBeVisible();
    // an outage was not a logout
    expect((await page.request.get("/api/auth/me")).status()).toBe(200);
  });

  test("[OUT-01] the same on every protected page and for every role", async ({ page }) => {
    for (const [role, path] of [["admin", "/admin/dashboard"], ["coordinator", "/coordinator/donations"], ["manager", "/pantry"]] as const) {
      await page.context().clearCookies();
      await setFault("none");
      await login(page, role);
      await setFault("db_down");
      await page.goto(path);
      await expect(page.getByRole("heading", { name: /temporarily unavailable/ }), `${role} ${path}`).toBeVisible();
    }
  });

  test("[OUT-03] pressing Run forecast during an outage explains it and the page stays usable", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/forecasts");
    await setFault("db_down");
    await page.getByRole("button", { name: /Run forecast/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: /temporarily unavailable/ }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Run forecast/ })).toBeEnabled();
    await setFault("none");
    await page.getByRole("button", { name: /Run forecast/ }).click();
    await expect(page.getByText(/saved in/)).toBeVisible({ timeout: 30_000 });
  });

  test("[OUT-04] going offline shows a banner and a clear message", async ({ page, context }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/forecasts");
    await context.setOffline(true);
    await expect(page.getByRole("alert").filter({ hasText: /You're offline/ }).first()).toBeVisible();
    await page.getByRole("button", { name: /Run forecast/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: /offline/i }).first()).toBeVisible();
    await context.setOffline(false);
    await expect(page.getByText(/Changes can't be saved/)).toHaveCount(0);
  });

  test("[OUT-05] a call that never answers ends with a readable timeout message", async ({ page }) => {
    await login(page, "coordinator");
    await page.clock.install();
    await page.route(/\/api\/forecasts\/run$/, () => {
      /* never answer */
    });
    await open(page, "/coordinator/forecasts");
    await page.getByRole("button", { name: /Run forecast/ }).click();
    await expect(page.getByText(/Training the model/)).toBeVisible();
    await page.clock.fastForward(125_000);
    await expect(page.getByRole("alert").filter({ hasText: /taking longer than expected/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Run forecast/ })).toBeEnabled();
  });

  test("[OUT-06] an unhandled promise rejection shows a dismissible banner", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator");
    await page.evaluate(() => {
      void Promise.reject(new Error("nobody caught this"));
    });
    const banner = page.getByRole("alert").filter({ hasText: /Something went wrong in the background/ });
    await expect(banner).toBeVisible();
    await banner.getByRole("button", { name: "Dismiss" }).click();
    await expect(banner).toHaveCount(0);
  });
});

test.describe("page states", () => {
  test("[PANT-03] an empty pantry list says so", async ({ page }) => {
    await login(page, "coordinator");
    await setFault("empty_pantries");
    await open(page, "/coordinator");
    await expect(page.getByText(/No pantries yet/)).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
  });

  test("[SHELL-11] a loading screen shows while a page waits for the API", async ({ page }) => {
    await login(page, "coordinator");
    await setFault("slow");
    await page.goto("/coordinator/forecasts", { waitUntil: "commit" });
    await expect(page.getByText("Loading…")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Forecasts" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Loading…")).toHaveCount(0);
  });

  test("[SHELL-12] a page whose data request fails shows Something went wrong with Try again", async ({ page }) => {
    await login(page, "coordinator");
    await setFault("api_error");
    await page.goto("/coordinator");
    await expect(page.getByRole("heading", { name: "Something went wrong" })).toBeVisible();
    await setFault("none");
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { name: "Pantries" })).toBeVisible();
  });
});
