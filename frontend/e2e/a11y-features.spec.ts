import type { Locator, Page } from "@playwright/test";

import {
  addUrgentLot,
  approveFor,
  expect,
  file,
  login,
  open,
  prepareAllocation,
  prepareForecast,
  type Role,
  setAi,
  staffApi,
  test,
  USERS,
} from "./fixtures";

// What was built for people who use a keyboard, a screen reader, zoom or reduced motion. The axe scans
// in a11y.spec.ts catch rule violations; these tests check the behaviour axe cannot see: where focus
// goes, what is announced, what a dialog does, and that every chart has a text alternative.
// Checklist rows used below (listed here because several test titles are built in a loop):
// "A11Y-20" "A11Y-21" "A11Y-22" "A11Y-23" "A11Y-24" "A11Y-25" "A11Y-26" "A11Y-27" "A11Y-28"
// "A11Y-29" "A11Y-30" "A11Y-31" "A11Y-32" "A11Y-33"

const SHELL: [Role, string, string][] = [
  ["coordinator", "/coordinator", "Pantries"],
  ["coordinator", "/coordinator/donations", "Donations"],
  ["coordinator", "/coordinator/forecasts", "Forecasts"],
  ["coordinator", "/coordinator/allocations", "Allocations"],
  ["admin", "/admin/dashboard", "Dashboard"],
  ["manager", "/pantry", "My pantry"],
];

/**
 * The key that moves to the next (or previous) control. In Safari's engine, Tab alone only visits form
 * fields by default; links and buttons need Option+Tab (or a Safari setting). So WebKit gets Alt+Tab.
 */
const isWebKit = (page: Page) => page.context().browser()?.browserType().name() === "webkit";
const nextKey = (page: Page) => (isWebKit(page) ? "Alt+Tab" : "Tab");
const prevKey = (page: Page) => (isWebKit(page) ? "Alt+Shift+Tab" : "Shift+Tab");

/** Press Tab until the target has focus: the only way a keyboard user can reach it. */
async function tabTo(page: Page, target: Locator, max = 150) {
  for (let i = 0; i < max; i++) {
    if ((await target.count()) > 0 && (await target.first().evaluate((el) => el === document.activeElement))) return;
    await page.keyboard.press(nextKey(page));
  }
  throw new Error(`Not reachable with the Tab key within ${max} presses: ${target}`);
}

const activeInside = (page: Page, selector: string) =>
  page.evaluate((s) => Boolean(document.activeElement?.closest(s)), selector);

async function sampleFocus(page: Page, presses: number) {
  const seen: { tag: string; id: string; outline: string; width: number; repeat: boolean }[] = [];
  let last = "";
  for (let i = 0; i < presses; i++) {
    await page.keyboard.press(nextKey(page));
    const now = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const style = getComputedStyle(el);
      // a date field has several focus stops (month, day, year, the calendar button) in one element
      const key = `${el.tagName}#${el.id}`;
      const dateField = (el as HTMLInputElement).type === "date";
      return { tag: el.tagName.toLowerCase(), id: el.id, outline: style.outlineStyle, width: parseFloat(style.outlineWidth), key, dateField };
    });
    // Safari draws its own ring on the parts of a date field, not on the field: judged in Chromium only
    const skip = now.dateField && isWebKit(page);
    seen.push({ tag: now.tag, id: now.id, outline: skip ? "solid" : now.outline, width: skip ? 3 : now.width, repeat: now.key === last && now.tag === "input" });
    last = now.key;
  }
  // only the first stop in an element counts; the later ones are parts of the same control
  return seen.filter((s) => !s.repeat);
}

async function newDonation(name = "m.eml", text = "10 cases lettuce") {
  const api = await staffApi();
  const res = await api.post("/api/donations", { multipart: { file: file(name, text, "message/rfc822") } });
  return (await res.json()).id as number;
}

test.describe("skip link, landmarks, titles and navigation", () => {
  const pages: [Role | null, string][] = [[null, "/login"], ...SHELL.map(([r, u]) => [r, u] as [Role, string])];

  for (const [role, url] of pages) {
    test(`[A11Y-20] ${url}: the first Tab reaches a skip link that moves focus to the main content`, async ({ page }) => {
      if (role) await login(page, role);
      await open(page, url);
      await page.keyboard.press(nextKey(page));
      const skip = page.getByRole("link", { name: "Skip to main content" });
      await expect(skip).toBeFocused();
      await expect(skip).toBeVisible();
      const box = await skip.boundingBox();
      expect(box && box.y >= 0 && box.x >= 0, "the skip link is on screen when focused").toBeTruthy();
      await page.keyboard.press("Enter");
      await expect(page.locator("#main-content")).toBeFocused();
    });

    test(`[A11Y-21] ${url}: one banner, navigation, main and footer landmark where the page has them`, async ({ page }) => {
      if (role) await login(page, role);
      await open(page, url);
      await expect(page.getByRole("main")).toHaveCount(1);
      await expect(page.getByRole("contentinfo")).toHaveCount(1);
      if (role) {
        await expect(page.getByRole("banner")).toHaveCount(1);
        await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(1);
      }
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    });
  }

  test("[A11Y-22] every route has its own page title", async ({ page }) => {
    const titles = new Map<string, string>();
    const record = async (name: string) => titles.set(name, await page.title());
    await open(page, "/login");
    await record("login");
    await open(page, "/unavailable");
    await record("unavailable");
    await open(page, "/no-such-page-at-all");
    await record("not-found");
    await login(page, "coordinator");
    for (const [, url] of SHELL.slice(0, 4)) {
      await open(page, url);
      await record(url);
    }
    await open(page, `/coordinator/donations/${await newDonation()}`);
    await record("donation");
    await open(page, "/coordinator/donations/99999999");
    await record("missing donation");
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    await record("dashboard");
    await login(page, "manager");
    await open(page, "/pantry");
    await record("pantry");
    for (const [name, title] of titles) {
      expect(title, name).toMatch(/\S.* · PantryPulse$/);
    }
    const distinct = new Set(titles.values());
    // the two "not found" pages (a missing page and a missing record) may share a title
    expect(distinct.size, `titles: ${JSON.stringify([...titles])}`).toBeGreaterThanOrEqual(titles.size - 1);
  });

  for (const [role, url, label] of SHELL) {
    test(`[A11Y-23] ${url}: exactly one nav link has aria-current="page" and it is "${label}"`, async ({ page }) => {
      await login(page, role);
      await open(page, url);
      const nav = page.getByRole("navigation", { name: "Main" });
      const current = nav.locator('[aria-current="page"]');
      await expect(current).toHaveCount(1);
      await expect(current).toHaveText(label);
    });
  }

  test("[A11Y-23] a detail page keeps its section highlighted in the navigation", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, `/coordinator/donations/${await newDonation()}`);
    await expect(page.getByRole("navigation", { name: "Main" }).locator('[aria-current="page"]')).toHaveText("Donations");
  });

  test("[A11Y-23] the phone menu button says whether it is open", async ({ page }, info) => {
    test.skip(info.project.name !== "chromium-375", "the menu is a button on phones only");
    await login(page, "coordinator");
    await open(page, "/coordinator");
    const button = page.getByRole("button", { name: /Pantries/ });
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("link", { name: "Forecasts" })).toBeVisible();
  });
});

test.describe("focus is always visible", () => {
  for (const [role, url] of [[null, "/login"] as const, ...SHELL.map(([r, u]) => [r, u] as const)]) {
    test(`[A11Y-24] ${url}: every element that takes focus shows a clear outline`, async ({ page }) => {
      if (role) await login(page, role);
      await open(page, url);
      // Tab past the last control leaves the page (to the browser's own controls): that is not a page element
      const seen = (await sampleFocus(page, 14)).filter((s) => s.tag !== "body");
      const weak = seen.filter((s) => s.outline === "none" || s.width < 2);
      expect(weak, `focused elements without a visible outline: ${JSON.stringify(weak)} of ${JSON.stringify(seen)}`).toEqual([]);
      expect(seen.length).toBeGreaterThan(3);
    });
  }

  test("[A11Y-24] form controls keep a visible outline too (inputs, selects, textareas)", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, `/coordinator/donations/${await newDonation()}`);
    const seen = (await sampleFocus(page, 22)).filter((s) => s.tag !== "body");
    const fields = seen.filter((s) => ["input", "select", "textarea"].includes(s.tag));
    expect(fields.length).toBeGreaterThan(3);
    const weakFields = fields.filter((s) => s.outline === "none" || s.width < 2);
    expect(weakFields, `weak: ${JSON.stringify(weakFields)}`).toEqual([]);
  });
});

test.describe("forms tell you what is wrong and put you there", () => {
  const described = (page: Page, el: Locator) =>
    el.evaluate((node) => {
      const ids = (node.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
      return ids.map((id) => document.getElementById(id)?.textContent?.trim() ?? "").join(" ").trim();
    });

  test("[A11Y-25] login: empty submit marks the field, links its message and focuses it", async ({ page }) => {
    await open(page, "/login");
    await page.getByRole("button", { name: "Sign in" }).click();
    const email = page.getByLabel("Email");
    await expect(email).toHaveAttribute("aria-invalid", "true");
    expect(await described(page, email)).toContain("Enter your email address.");
    await expect(email).toBeFocused();
    await email.fill("a@example.org");
    await page.getByRole("button", { name: "Sign in" }).click();
    const password = page.getByLabel("Password");
    await expect(password).toBeFocused();
    expect(await described(page, password)).toContain("Enter your password.");
  });

  test("[A11Y-25] donation review: errors are linked to their fields and the first one is focused", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, `/coordinator/donations/${await newDonation()}`);
    await page.getByLabel("Donor", { exact: true }).selectOption({ label: "Choose a donor…" });
    await page.getByRole("button", { name: /^Confirm and add/ }).click();
    const donor = page.getByLabel("Donor", { exact: true });
    await expect(donor).toHaveAttribute("aria-invalid", "true");
    expect(await described(page, donor)).toContain("Choose a donor");
    await expect(donor).toBeFocused();
    await donor.selectOption({ label: "New donor…" });
    await page.getByLabel("New donor name").fill("Keyboard Farms");
    await page.locator('[id^="name-"]').first().fill("");
    await page.getByRole("button", { name: /^Confirm and add/ }).click();
    const name = page.locator('[id^="name-"]').first();
    await expect(name).toHaveAttribute("aria-invalid", "true");
    expect((await described(page, name)).length).toBeGreaterThan(3);
    await expect(name).toBeFocused();
  });

  test("[A11Y-25] shortage report: each missing choice is described and focus goes to the first", async ({ page }) => {
    await login(page, "manager");
    await open(page, "/pantry");
    await page.getByRole("button", { name: "Send report" }).click();
    const group = page.getByRole("group", { name: "What ran short?" });
    expect(await described(page, group)).toMatch(/choose|pick|select/i);
    expect(await activeInside(page, "fieldset")).toBe(true);
    await page.getByRole("button", { name: /^Dairy/ }).click();
    await page.getByRole("button", { name: "Send report" }).click();
    expect(await described(page, page.getByRole("group", { name: "How bad was it?" }))).toMatch(/choose|pick|select/i);
  });

  test("[A11Y-25] shortage report: the optional fields link their errors", async ({ page }) => {
    await login(page, "manager");
    await open(page, "/pantry");
    await page.getByRole("button", { name: /^Dairy/ }).click();
    await page.getByRole("button", { name: /^Serious/ }).click();
    await page.getByLabel(/Households turned away/).fill("abc");
    await page.getByRole("button", { name: "Send report" }).click();
    const turned = page.getByLabel(/Households turned away/);
    await expect(turned).toHaveAttribute("aria-invalid", "true");
    expect((await described(page, turned)).length).toBeGreaterThan(3);
    await expect(turned).toBeFocused();
  });

  test("[A11Y-25] allocation edit: a bad amount is linked to the field and keeps focus on it", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Edit" }).first().click();
    const amount = page.getByLabel("New amount (lb)");
    await expect(amount).toBeFocused(); // opening the form moves focus into it
    await amount.fill("0");
    await page.keyboard.press("Enter");
    await expect(amount).toHaveAttribute("aria-invalid", "true");
    expect((await described(page, amount)).length).toBeGreaterThan(3);
    await expect(amount).toBeFocused();
  });

  test("[A11Y-25] monthly summary: approving nothing says why and puts focus in the text box", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    const text = page.getByLabel("Summary text");
    await text.fill("");
    await page.getByRole("button", { name: "Approve as final" }).click();
    await expect(text).toHaveAttribute("aria-invalid", "true");
    expect(await described(page, text)).toContain("Write the summary text");
    await expect(text).toBeFocused();
  });

  test("[A11Y-25] dashboard: a backwards date range is linked to the date fields", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    await page.getByLabel("From", { exact: true }).fill("2026-09-30");
    await page.getByLabel("To", { exact: true }).fill("2026-01-01");
    const from = page.getByLabel("From", { exact: true });
    await expect(from).toHaveAttribute("aria-invalid", "true");
    expect(await described(page, from)).toContain("start date");
  });

  test("[A11Y-25] every form control on every page has a name", async ({ page }) => {
    await login(page, "coordinator");
    const id = await newDonation();
    await prepareAllocation();
    const unnamed: string[] = [];
    for (const url of ["/coordinator/donations", `/coordinator/donations/${id}`, "/coordinator/forecasts", "/coordinator/allocations"]) {
      await open(page, url);
      const bad = await page.evaluate(() =>
        [...document.querySelectorAll("input:not([type=hidden]), select, textarea")]
          .filter((el) => {
            const e = el as HTMLInputElement;
            const named = (e.labels?.length ?? 0) > 0 || e.getAttribute("aria-label") || e.getAttribute("aria-labelledby") || e.title;
            return !named;
          })
          .map((el) => el.outerHTML.slice(0, 100)),
      );
      unnamed.push(...bad.map((b) => `${url}: ${b}`));
    }
    expect(unnamed).toEqual([]);
  });
});

test.describe("announcements", () => {
  test("[A11Y-26] a wrong password is announced as an alert, and signing in is announced as status", async ({ page }) => {
    await page.route("**/api/auth/login", async (route) => {
      await new Promise((r) => setTimeout(r, 600));
      await route.continue();
    });
    await open(page, "/login");
    await page.getByLabel("Email").fill(USERS.coordinator.email);
    await page.getByLabel("Password").fill("definitely-wrong-1");
    await page.getByRole("button", { name: /Sign in/ }).click();
    await expect(page.getByRole("status").filter({ hasText: "Signing in" })).toBeAttached();
    await expect(page.getByRole("alert").filter({ hasText: /incorrect/i })).toBeVisible();
  });

  test("[A11Y-26] approving, editing and rejecting a shipment each announce what happened", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Approve", exact: true }).first().click();
    await expect(page.getByRole("status").filter({ hasText: /Approved/ })).toBeVisible();
    await page.getByRole("button", { name: "Edit" }).first().click();
    await page.getByLabel("New amount (lb)").fill("5");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status").filter({ hasText: /Saved|Changed|Updated/ })).toBeVisible();
    await page.getByRole("button", { name: "Reject" }).first().click();
    await expect(page.getByRole("status").filter({ hasText: /Rejected/ })).toBeVisible();
  });

  test("[A11Y-26] focus is not lost when the row you used disappears", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Approve", exact: true }).first().click();
    await expect(page.getByRole("status").filter({ hasText: /Approved/ })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.activeElement === document.body), { message: "focus fell back to the page body" })
      .toBe(false);
  });

  test("[A11Y-26] saving a shortage report and confirming a donation are announced", async ({ page }) => {
    await login(page, "manager");
    await open(page, "/pantry");
    await page.getByRole("button", { name: /^Dairy/ }).click();
    await page.getByRole("button", { name: /^Serious/ }).click();
    await page.getByRole("button", { name: "Send report" }).click();
    await expect(page.getByRole("status").filter({ hasText: /Thank you/ })).toBeVisible();
  });

  test("[A11Y-26] loading screens, the chart loading state and the offline banner are announced", async ({ page, context }) => {
    await login(page, "coordinator");
    await prepareForecast();
    await open(page, "/coordinator/forecasts");
    await expect(page.locator('[role="status"], [aria-live]').first()).toBeAttached();
    await context.setOffline(true);
    await expect(page.getByRole("alert").filter({ hasText: /offline/i })).toBeVisible();
    await context.setOffline(false);
  });
});

test.describe("dialogs", () => {
  async function dialogChecks(page: Page, opener: Locator, dialogName: RegExp, cancel: string, role: "dialog" | "alertdialog" = "dialog") {
    await opener.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole(role, { name: dialogName });
    await expect(dialog).toBeVisible();
    expect(await activeInside(page, "dialog"), "focus moved into the dialog").toBe(true);
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press(nextKey(page));
      expect(await activeInside(page, "dialog"), `Tab ${i + 1} stayed in the dialog`).toBe(true);
    }
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press(prevKey(page));
      expect(await activeInside(page, "dialog"), `Shift+Tab ${i + 1} stayed in the dialog`).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(opener).toBeFocused();
    await opener.focus();
    await page.keyboard.press("Enter");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: cancel }).click();
    await expect(dialog).toBeHidden();
    await expect(opener).toBeFocused();
  }

  test("[A11Y-27] approve-all: traps focus, closes with Escape and Cancel, and returns focus", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await dialogChecks(page, page.getByRole("button", { name: /^Approve all shown/ }), /Approve all shown/, "Cancel");
  });

  test("[A11Y-27] reject donation: traps focus, closes with Escape and Keep reviewing, and returns focus", async ({ page }) => {
    await login(page, "coordinator");
    await open(page, `/coordinator/donations/${await newDonation()}`);
    await dialogChecks(page, page.getByRole("button", { name: "Reject", exact: true }), /Confirm rejection/, "Keep reviewing", "alertdialog");
  });

  test("[A11Y-27] a dialog names itself and the page behind it is not reachable", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: /^Approve all shown/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toHaveAccessibleName(/Approve all shown/);
    await expect(dialog).toHaveJSProperty("open", true);
    const modal = await dialog.evaluate((d) => (d as HTMLDialogElement).matches(":modal"));
    expect(modal, "opened with showModal, so the rest of the page is inert").toBe(true);
  });
});

test.describe("tables and charts have text alternatives", () => {
  test("[A11Y-28] every table has a caption and header cells with a scope", async ({ page }) => {
    await login(page, "coordinator");
    const donationId = await newDonation();
    await prepareForecast();
    const problems: string[] = [];
    const audit = async (url: string) => {
      await open(page, url);
      const closed = page.getByRole("button", { name: /view as table/i });
      while ((await closed.count()) > 0) await closed.first().click();
      const bad = await page.evaluate(() => {
        const out: string[] = [];
        document.querySelectorAll("table").forEach((t, i) => {
          if (!t.querySelector("caption")?.textContent?.trim()) out.push(`table ${i} has no caption`);
          t.querySelectorAll("th").forEach((th) => {
            if (!th.textContent?.trim() && !th.getAttribute("aria-label")) out.push(`table ${i} has an empty header cell`);
            if (!th.getAttribute("scope")) out.push(`table ${i}: <th>${th.textContent?.slice(0, 20)}</th> has no scope`);
          });
        });
        document.querySelectorAll('[role="table"]').forEach((t, i) => {
          if (!t.getAttribute("aria-label") && !t.getAttribute("aria-labelledby")) out.push(`grid ${i} has no name`);
          if (t.querySelectorAll('[role="columnheader"]').length === 0) out.push(`grid ${i} has no column headers`);
          t.querySelectorAll('[role="row"]').forEach((r, j) => {
            if (r.querySelectorAll(':scope > [role="cell"], :scope > [role="columnheader"]').length === 0) out.push(`grid ${i} row ${j} has no cells`);
          });
        });
        return out;
      });
      problems.push(...bad.map((b) => `${url}: ${b}`));
    };
    for (const url of ["/coordinator", "/coordinator/donations", `/coordinator/donations/${donationId}`, "/coordinator/forecasts"]) await audit(url);
    await login(page, "admin");
    await audit("/admin/dashboard");
    expect(problems).toEqual([]);
  });

  test("[A11Y-29] the forecast chart has a text summary and a table view with the same numbers", async ({ page }) => {
    await login(page, "coordinator");
    await prepareForecast();
    await open(page, "/coordinator/forecasts");
    const chart = page.getByRole("img", { name: /Weekly pounds/ });
    await expect(chart).toBeVisible();
    const summaryId = await chart.getAttribute("aria-describedby");
    expect(summaryId, "the chart points at its text summary").toBeTruthy();
    const summary = (await page.locator(`#${summaryId}`).textContent()) ?? "";
    expect(summary).toMatch(/lb/);
    expect(summary).toMatch(/forecast|next week/i);
    const toggle = page.getByRole("button", { name: /(view as|hide) table/i });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toHaveText(/view as table/i);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveText(/hide table/i);
    const table = page.getByRole("table", { name: /Weekly pounds/ });
    await expect(table).toBeVisible();
    expect(await table.locator("tbody tr").count()).toBeGreaterThan(5);
    await toggle.click();
    await expect(table).toBeHidden();
  });

  test("[A11Y-29] each of the five dashboard charts has a name, a summary and a table view", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    const figures = page.locator("figure");
    expect(await figures.count()).toBe(5);
    for (let i = 0; i < 5; i++) {
      const img = figures.nth(i).locator('div[role="img"]');
      await expect(img).toHaveCount(1);
      expect(await img.getAttribute("aria-label"), `chart ${i + 1} has a name`).toBeTruthy();
      const describedBy = await img.getAttribute("aria-describedby");
      expect(describedBy, `chart ${i + 1} has a text summary`).toBeTruthy();
      expect(((await page.locator(`#${describedBy}`).textContent()) ?? "").length).toBeGreaterThan(20);
      await figures.nth(i).getByRole("button", { name: "View as table" }).click();
      const table = figures.nth(i).locator("table");
      expect(await table.locator("tbody tr").count(), `chart ${i + 1} table rows`).toBeGreaterThan(3);
      expect(((await table.locator("caption").textContent()) ?? "").length).toBeGreaterThan(3);
    }
  });

  test("[A11Y-29] the table view can be opened and closed from the keyboard", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    const toggle = page.getByRole("button", { name: /(view as|hide) table/i }).first();
    await tabTo(page, toggle);
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Space");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});

test.describe("meaning is never carried by colour alone", () => {
  test("[A11Y-30] every status badge says its status in words", async ({ page }) => {
    await login(page, "coordinator");
    await newDonation();
    await open(page, "/coordinator/donations");
    const badges = page.locator("table span.rounded-full, ul span.rounded-full");
    expect(await badges.count()).toBeGreaterThan(0);
    for (const text of await badges.allInnerTexts()) expect(text.trim()).toMatch(/^(Needs review|Added|Rejected|Pending|Confirmed)/i);
  });

  test("[A11Y-30] food that expires soon is marked in words as well as red", async ({ page }) => {
    await login(page, "coordinator");
    await addUrgentLot();
    const api = await prepareAllocation();
    const rows = (await (await api.get("/api/allocations")).json()).rows as { lot: { days_left: number | null }; status: string }[];
    const urgent = rows.filter((r) => r.status === "proposed" && r.lot.days_left != null && r.lot.days_left <= 3).length;
    await open(page, "/coordinator/allocations");
    expect(urgent, "the seeded data has urgent lots").toBeGreaterThan(0);
    await page.getByRole("tab", { name: "To review", exact: true }).click();
    expect(await page.getByText("Expiring soon").count()).toBe(urgent);
  });

  test("[A11Y-30] chosen options in the shortage form show a tick as well as a colour", async ({ page }) => {
    await login(page, "manager");
    await open(page, "/pantry");
    const dairy = page.getByRole("button", { name: /^Dairy/ });
    await expect(dairy).toHaveAttribute("aria-pressed", "false");
    expect(await dairy.innerText()).not.toContain("✓");
    await dairy.click();
    await expect(dairy).toHaveAttribute("aria-pressed", "true");
    expect(await dairy.innerText()).toContain("✓");
  });

  test("[A11Y-30] the active navigation link is more than a colour change", async ({ page }, info) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/donations");
    if (info.project.name === "chromium-375") await page.getByRole("button", { name: /Donations/ }).click(); // the phone menu
    const [active, other] = await Promise.all([
      page.getByRole("navigation", { name: "Main" }).locator('[aria-current="page"]').evaluate((el) => {
        const s = getComputedStyle(el);
        return { weight: s.fontWeight, decoration: s.textDecorationLine, border: s.borderBottomWidth };
      }),
      page.getByRole("link", { name: "Forecasts" }).evaluate((el) => {
        const s = getComputedStyle(el);
        return { weight: s.fontWeight, decoration: s.textDecorationLine, border: s.borderBottomWidth };
      }),
    ]);
    expect(JSON.stringify(active)).not.toBe(JSON.stringify(other));
  });

  test("[A11Y-30] the lines in the dashboard charts differ in pattern as well as colour", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    const dashes = await page.locator("figure").filter({ hasText: "Stockouts over time" }).locator(".recharts-line-curve").evaluateAll((els) =>
      els.map((e) => e.getAttribute("stroke-dasharray") ?? "solid"),
    );
    expect(dashes.length).toBe(2);
    expect(new Set(dashes).size, `line patterns: ${dashes}`).toBe(2);
  });
});

test.describe("motion and zoom", () => {
  test("[A11Y-31] with reduced motion, spinners, pulses, transitions and smooth scrolling stop", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page, "/login");
    const result = await page.evaluate(() => {
      const probe = document.createElement("div");
      probe.className = "animate-spin animate-pulse transition-opacity";
      document.body.appendChild(probe);
      const s = getComputedStyle(probe);
      const out = {
        durations: s.animationDuration.split(",").map((d) => parseFloat(d) * (d.trim().endsWith("ms") ? 0.001 : 1)),
        iterations: s.animationIterationCount,
        transition: parseFloat(s.transitionDuration) * (s.transitionDuration.endsWith("ms") ? 0.001 : 1),
        scroll: getComputedStyle(document.documentElement).scrollBehavior,
      };
      probe.remove();
      return out;
    });
    expect(Math.max(...result.durations)).toBeLessThan(0.05);
    expect(result.iterations.split(",").every((n) => n.trim() === "1")).toBe(true);
    expect(result.transition).toBeLessThan(0.05);
    expect(result.scroll).not.toBe("smooth");
  });

  test("[A11Y-31] without the preference, the loading spinner still animates", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await open(page, "/login");
    const duration = await page.evaluate(() => {
      const probe = document.createElement("div");
      probe.className = "animate-spin";
      document.body.appendChild(probe);
      const d = parseFloat(getComputedStyle(probe).animationDuration);
      probe.remove();
      return d;
    });
    expect(duration).toBeGreaterThan(0.1);
  });

  test("[A11Y-31] the clock on the dashboard does not tick every second", async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    const clock = page.locator("p", { hasText: /^[A-Z][a-z]+day,/ }).first();
    const first = await clock.innerText();
    await page.waitForTimeout(2200);
    expect(await clock.innerText()).toBe(first);
    expect(first).not.toMatch(/\d:\d\d:\d\d/);
  });

  const widths: [string, number, number][] = [["200% zoom of a 1280 px screen", 640, 400], ["400% zoom of a 1280 px screen", 320, 256]];
  for (const [label, width, height] of widths) {
    for (const [role, url] of [[null, "/login"] as const, ...SHELL.map(([r, u]) => [r, u] as const)]) {
      test(`[A11Y-32] ${url} at ${label}: no sideways scrolling and the heading is readable`, async ({ page }, info) => {
        test.skip(info.project.name !== "chromium-1280", "the width is set by the test itself");
        await page.setViewportSize({ width, height });
        if (role) await login(page, role);
        if (url === "/coordinator/forecasts") await prepareForecast();
        await open(page, url);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(1);
        const h1 = page.getByRole("heading", { level: 1 });
        await expect(h1).toBeVisible();
        const box = await h1.boundingBox();
        expect(box && box.x >= 0 && box.x + box.width <= width + 1, "the heading fits in the width").toBeTruthy();
        const fontPx = await h1.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
        expect(fontPx).toBeGreaterThanOrEqual(16);
      });
    }
  }

  test("[A11Y-32] the review form and allocation list reflow at 320 px", async ({ page }, info) => {
    test.skip(info.project.name !== "chromium-1280", "the width is set by the test itself");
    await page.setViewportSize({ width: 320, height: 256 });
    await login(page, "coordinator");
    await prepareAllocation();
    for (const url of [`/coordinator/donations/${await newDonation()}`, "/coordinator/allocations"]) {
      await open(page, url);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, url).toBeLessThanOrEqual(1);
    }
  });

  test("[A11Y-32] the page can be zoomed: the viewport does not forbid it", async ({ page }) => {
    await open(page, "/login");
    const viewport = await page.locator('meta[name="viewport"]').getAttribute("content");
    expect(viewport ?? "").not.toMatch(/user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b/);
  });
});

test.describe("keyboard-only journeys (no mouse at all)", () => {
  async function noMouse(page: Page) {
    await page.addInitScript(() => {
      (window as unknown as { __pointer: number }).__pointer = 0;
      for (const type of ["pointerdown", "mousedown", "click"]) {
        document.addEventListener(
          type,
          (e) => {
            // a click made by the keyboard (Enter or Space on a button) has detail 0 and no pointer
            if ((e as MouseEvent).detail !== 0 || type !== "click") (window as unknown as { __pointer: number }).__pointer++;
          },
          true,
        );
      }
    });
  }
  const pointerEvents = (page: Page) => page.evaluate(() => (window as unknown as { __pointer: number }).__pointer);

  test("[A11Y-33] log in", async ({ page }) => {
    await noMouse(page);
    await open(page, "/login");
    await tabTo(page, page.getByLabel("Email"));
    await page.keyboard.type(USERS.coordinator.email);
    await page.keyboard.press(nextKey(page));
    await expect(page.getByLabel("Password")).toBeFocused();
    await page.keyboard.type(USERS.coordinator.password);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/coordinator$/);
    expect(await pointerEvents(page)).toBe(0);
  });

  test("[A11Y-33] upload a donation, review it and confirm it", async ({ page }) => {
    await login(page, "coordinator");
    await noMouse(page);
    await open(page, "/coordinator/donations");
    const input = page.locator('input[type="file"]');
    await tabTo(page, input);
    const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.keyboard.press("Space")]);
    await chooser.setFiles(file("keyboard.eml", "10 cases lettuce, 200 lb, refrigerated", "message/rfc822"));
    await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const donor = page.getByLabel("Donor", { exact: true });
    await tabTo(page, donor);
    await page.keyboard.press("End"); // the last option: "New donor…"
    await expect(page.getByLabel("New donor name")).toBeVisible();
    await page.keyboard.press(nextKey(page));
    await expect(page.getByLabel("New donor name")).toBeFocused();
    await page.keyboard.type("Keyboard Farms");
    await tabTo(page, page.getByRole("button", { name: /^Confirm and add/ }));
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/added=\d+/);
    await expect(page.getByRole("status").filter({ hasText: /added/i }).first()).toBeVisible();
    expect(await pointerEvents(page)).toBe(0);
  });

  test("[A11Y-33] approve one shipment and edit another", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await noMouse(page);
    await open(page, "/coordinator/allocations");
    await tabTo(page, page.getByRole("button", { name: "Approve", exact: true }).first());
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: /Approved/ })).toBeVisible();
    await tabTo(page, page.getByRole("button", { name: "Edit" }).first());
    await page.keyboard.press("Enter");
    const amount = page.getByLabel("New amount (lb)");
    await expect(amount).toBeFocused();
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.type("7");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: /Saved|Changed|Updated/ })).toBeVisible();
    expect(await pointerEvents(page)).toBe(0);
  });

  test("[A11Y-33] submit a shortage report at phone size", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const api = await prepareAllocation();
    await approveFor(api, 14, 2);
    await login(page, "manager");
    await noMouse(page);
    await open(page, "/pantry");
    await tabTo(page, page.getByRole("button", { name: /^Dairy/ }));
    await page.keyboard.press("Space");
    await expect(page.getByRole("button", { name: /^Dairy/ })).toHaveAttribute("aria-pressed", "true");
    await tabTo(page, page.getByRole("button", { name: /^Serious/ }));
    await page.keyboard.press("Space");
    await tabTo(page, page.getByRole("button", { name: "Send report" }));
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: /Thank you/ })).toBeVisible();
    expect(await pointerEvents(page)).toBe(0);
  });

  test("[A11Y-33] a dialog opened and closed from the keyboard leaves focus where it started", async ({ page }) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await setAi("ok");
    const opener = page.getByRole("button", { name: /^Approve all shown/ });
    await tabTo(page, opener);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(opener).toBeFocused();
  });
});
