import type { Page } from "@playwright/test";

import { expect, file, isNarrow, isPhoneOrTablet, login, open, type Role, staffApi, test, USERS } from "./fixtures";

const menuButton = (page: Page) => page.locator('button[aria-controls="main-menu"]');

/** Below 768 px the navigation is a menu: open it so the links can be reached. */
async function revealNav(page: Page) {
  const button = menuButton(page);
  if ((await button.count()) && (await button.isVisible()) && (await button.getAttribute("aria-expanded")) === "false") {
    await button.click();
  }
  return page.getByRole("navigation", { name: "Main" });
}

const NAV: Record<Role, string[]> = {
  coordinator: ["Pantries", "Donations", "Forecasts", "Allocations"],
  admin: ["Pantries", "Donations", "Forecasts", "Allocations", "Dashboard"],
  manager: ["My pantry"],
};

test.describe("header and navigation", () => {
  test("[SHELL-01] the header shows the app name, and the user from 640 px up", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator");
    await expect(page.getByText("PantryPulse", { exact: true })).toBeVisible();
    const width = page.viewportSize()?.width ?? 1280;
    const who = page.getByText("Demo Coordinator");
    if (width >= 640) await expect(who).toBeVisible();
    else await expect(who).toBeHidden();
  });

  test("[SHELL-02] Log out ends the session and protected pages redirect again", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator");
    await page.getByRole("button", { name: "Log out" }).dblclick();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/coordinator");
    await expect(page).toHaveURL(/\/login\?next=/);
    expect((await page.request.get("/api/auth/me")).status()).toBe(401);
  });

  for (const [id, role] of [["SHELL-03", "coordinator"], ["SHELL-04", "admin"], ["SHELL-05", "manager"]] as const) {
    test(`[${id}] ${role} sees exactly their navigation items`, async ({ page }) => {
      await login(page, role);
      await open(page, USERS[role].home);
      const nav = await revealNav(page);
      const names = await nav.getByRole("link").allInnerTexts();
      expect(names.map((n) => n.trim())).toEqual(NAV[role]);
    });
  }

  test("[SHELL-06] each navigation link opens its page and is marked current", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/coordinator");
    const targets: [string, RegExp][] = [
      ["Donations", /\/coordinator\/donations$/],
      ["Forecasts", /\/coordinator\/forecasts$/],
      ["Allocations", /\/coordinator\/allocations$/],
      ["Dashboard", /\/admin\/dashboard$/],
      ["Pantries", /\/coordinator$/],
    ];
    for (const [name, url] of targets) {
      const nav = await revealNav(page);
      await nav.getByRole("link", { name, exact: true }).click();
      await expect(page).toHaveURL(url);
      await page.waitForLoadState("networkidle");
      const again = await revealNav(page);
      await expect(again.getByRole("link", { name, exact: true })).toHaveAttribute("aria-current", "page");
    }
  });

  test("[SHELL-07] under 768 px the menu opens, closes and closes again on choosing a link", async ({ page }) => {
    test.skip(!isNarrow(page), "the menu only exists below 768 px");
    await login(page, "coordinator");
    await open(page, "/coordinator");
    const button = menuButton(page);
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByRole("link", { name: "Donations" })).toBeHidden();
    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("link", { name: "Donations" })).toBeVisible();
    await button.dblclick();
    const open_ = await button.getAttribute("aria-expanded");
    expect(["true", "false"]).toContain(open_);
    if (open_ === "false") await button.click();
    await page.getByRole("link", { name: "Donations" }).click();
    await expect(page).toHaveURL(/\/coordinator\/donations$/);
    await page.waitForLoadState("networkidle");
    await expect(menuButton(page)).toHaveAttribute("aria-expanded", "false");
  });

  test("[SHELL-08] pages of another role redirect to the user's own home", async ({ page }) => {
    const cases: [Role, string, RegExp][] = [
      ["coordinator", "/admin/dashboard", /\/coordinator$/],
      ["coordinator", "/pantry", /\/coordinator$/],
      ["admin", "/pantry", /\/coordinator$/],
      ["manager", "/coordinator", /\/pantry$/],
      ["manager", "/coordinator/donations", /\/pantry$/],
      ["manager", "/coordinator/forecasts", /\/pantry$/],
      ["manager", "/coordinator/allocations", /\/pantry$/],
      ["manager", "/admin/dashboard", /\/pantry$/],
    ];
    for (const [role, path, expected] of cases) {
      await page.context().clearCookies();
      await login(page, role);
      await page.goto(path);
      await expect(page, `${role} opening ${path}`).toHaveURL(expected);
    }
  });

  const smallControls = (page: Page) =>
    page.evaluate(() =>
      [...document.querySelectorAll("a,button,select,input,textarea,summary,[role=tab]")]
        .filter((e) => {
          const r = e.getBoundingClientRect();
          const type = (e as HTMLInputElement).type;
          return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden" &&
            !["hidden", "checkbox", "radio", "file"].includes(type) && r.height < 43.5 &&
            !(r.width <= 1 && r.height <= 1); // not the visually hidden skip link: it is 44 px tall when shown (A11Y-20)
        })
        .slice(0, 6)
        .map((e) => `${e.tagName}:${(e as HTMLElement).innerText?.slice(0, 20) ?? ""}:${Math.round(e.getBoundingClientRect().height)}`),
    );

  async function tooSmall(page: Page, paths: string[], role: Role): Promise<string[]> {
    const found: string[] = [];
    await page.context().clearCookies();
    await login(page, role);
    for (const path of paths) {
      await open(page, path);
      const nav = menuButton(page);
      if (await nav.isVisible()) await nav.click();
      found.push(...(await smallControls(page)).map((f) => `${path} ${f}`));
    }
    return found;
  }

  test("[SHELL-09] every control is at least 44 px tall on phones and tablets", async ({ page }) => {
    test.skip(!isPhoneOrTablet(page), "only checked below 1024 px");
    test.setTimeout(180_000);
    await open(page, "/login");
    const loginPage = (await smallControls(page)).map((f) => `/login ${f}`);
    const staff = await tooSmall(page, ["/coordinator", "/coordinator/forecasts", "/coordinator/allocations", "/admin/dashboard"], "admin");
    const manager = await tooSmall(page, ["/pantry"], "manager");
    expect([...loginPage, ...staff, ...manager]).toEqual([]);
  });

  test("[SHELL-09] the Donations page filter links and View links are at least 44 px tall", async ({ page }) => {
    test.skip(!isPhoneOrTablet(page), "only checked below 1024 px");
    const api = await staffApi("coordinator");
    await api.post("/api/donations", { multipart: { file: file("a.eml", "10 cases lettuce") } });
    expect(await tooSmall(page, ["/coordinator/donations"], "coordinator")).toEqual([]);
  });
});

test.describe("pantries page", () => {
  for (const [id, role] of [["PANT-01", "coordinator"], ["PANT-02", "admin"]] as const) {
    test(`[${id}] ${role} sees all 85 pantries in 6 counties`, async ({ page }) => {
      await login(page, role);
      await open(page, "/coordinator");
      await expect(page.getByRole("heading", { name: "Pantries" })).toBeVisible();
      await expect(page.getByText(/85 partner pantries/)).toBeVisible();
      await expect(page.getByText(/6 counties/)).toBeVisible();
      if (!isNarrow(page)) await expect(page.getByRole("row")).toHaveCount(86);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
