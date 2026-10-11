import type { Page } from "@playwright/test";

import {
  approveFor,
  countRequests,
  expect,
  failRequests,
  login,
  open,
  prepareAllocation,
  setAi,
  staffApi,
  test,
  WEIRD,
} from "./fixtures";

const noPwn = async (page: Page) =>
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
const sendReport = (page: Page) => page.getByRole("button", { name: /Send report|Update report/ });
const category = (page: Page, name: string) => page.getByRole("button", { name: new RegExp(`^${name}`) });
const severity = (page: Page, name: string) => page.getByRole("button", { name: new RegExp(`^${name}`) });
const turned = (page: Page) => page.getByLabel(/Households turned away/);
const note = (page: Page) => page.getByLabel(/^Note/);

test.describe("pantry portal", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "manager");
  });

  test("[PORT-01] with nothing approved the deliveries list says so", async ({ page }) => {
    await open(page, "/pantry");
    await expect(page.getByRole("heading", { name: "Pantry 14" })).toBeVisible();
    await expect(page.getByText(/Nothing is scheduled yet/)).toBeVisible();
  });

  test("[PORT-02][PORT-03] deliveries show item, pounds and dates, and only for this pantry", async ({ page }) => {
    const api = await prepareAllocation();
    await approveFor(api, 14, 3);
    await approveFor(api, 20, 2);
    await open(page, "/pantry");
    const cards = page.locator("section[aria-labelledby=incoming] > ul > li");
    await expect(cards).toHaveCount(3);
    await expect(cards.first()).toContainText(/lb/);
    await expect(cards.first()).toContainText(/Oct \d+/);
    await expect(cards.first()).toContainText(/use by/);
    const text = await page.locator("main").innerText();
    expect(text).not.toContain("Pantry 20");
  });

  test("[PORT-04] older deliveries sit under the details", async ({ page }) => {
    await open(page, "/pantry");
    await expect(page.getByText(/Delivered in the last week/)).toHaveCount(0);
  });

  test("[PORT-05][PORT-06] category and severity buttons select one at a time", async ({ page }) => {
    await open(page, "/pantry");
    for (const name of ["Produce", "Dairy", "Protein", "Bakery", "Frozen", "Canned", "Dry goods", "Beverages"]) {
      await category(page, name).click();
      await expect(category(page, name)).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator('button[aria-pressed="true"]').filter({ hasNotText: /Minor|Serious|Ran out/ })).toHaveCount(1);
    }
    for (const name of ["Minor", "Serious", "Ran out"]) {
      await severity(page, name).click();
      await expect(severity(page, name)).toHaveAttribute("aria-pressed", "true");
    }
  });

  test("[PORT-07] sending nothing shows what is missing and sends nothing", async ({ page }) => {
    await open(page, "/pantry");
    const sent = countRequests(page, "POST", /shortage-reports$/);
    await sendReport(page).click();
    await expect(page.getByText("Choose what ran short.")).toBeVisible();
    await expect(page.getByText("Choose how bad it was.")).toBeVisible();
    expect(sent.count()).toBe(0);
  });

  test("[PORT-08] households turned away: empty is fine, bad numbers are explained", async ({ page }) => {
    await open(page, "/pantry");
    await category(page, "Produce").click();
    await severity(page, "Minor").click();
    for (const bad of ["-1", "1.5", "abc", WEIRD.emoji, "100001"]) {
      await turned(page).fill(bad);
      await sendReport(page).click();
      await expect(page.locator("#turned ~ p[role=alert], p[role=alert]").filter({ hasText: /whole number|too many/ }).first()).toBeVisible();
    }
    await turned(page).fill(WEIRD.spaces);
    await sendReport(page).click();
    await expect(page.getByText(/Thank you/)).toBeVisible();
  });

  test("[PORT-09] the note is capped at 500 characters; HTML, emoji and SQL text are saved literally", async ({ page }) => {
    await open(page, "/pantry");
    await category(page, "Dairy").click();
    await severity(page, "Serious").click();
    await note(page).fill(WEIRD.long);
    await sendReport(page).click();
    await expect(page.getByText(/Keep the note under 500 characters/)).toBeVisible();
    await note(page).fill(`${WEIRD.html} ${WEIRD.sql} ${WEIRD.emoji} ${WEIRD.nonLatin}`);
    await sendReport(page).click();
    await expect(page.getByText(/Thank you/)).toBeVisible();
    await noPwn(page);
  });

  test("[PORT-10] a valid report is saved, the form clears and the category shows Reported this week", async ({ page }) => {
    await open(page, "/pantry");
    await category(page, "Protein").click();
    await severity(page, "Ran out").click();
    await turned(page).fill("12");
    await note(page).fill("Ran out on Friday");
    await sendReport(page).click();
    await expect(page.getByText(/Your protein report is saved/)).toBeVisible();
    await expect(category(page, "Protein")).toContainText("Reported this week");
    await expect(category(page, "Protein")).toHaveAttribute("aria-pressed", "false");
    await expect(note(page)).toHaveValue("");
  });

  test("[PORT-11][PORT-12] reporting the same category again updates it, and choosing it prefills the form", async ({ page }) => {
    await open(page, "/pantry");
    await category(page, "Dairy").click();
    await severity(page, "Minor").click();
    await sendReport(page).click();
    await expect(page.getByText(/Thank you/)).toBeVisible();
    await category(page, "Dairy").click();
    await expect(severity(page, "Minor")).toHaveAttribute("aria-pressed", "true");
    await severity(page, "Ran out").click();
    await sendReport(page).click();
    await expect(page.getByText(/Updated your dairy report/)).toBeVisible();
    const reports = await (await (await staffApi("manager")).get("/api/pantry/shortage-reports")).json();
    expect(reports).toHaveLength(1);
    expect(reports[0].severity).toBe(3);
  });

  test("[PORT-13] double-clicking Send sends one request", async ({ page }) => {
    await open(page, "/pantry");
    const sent = countRequests(page, "POST", /shortage-reports$/);
    await category(page, "Bakery").click();
    await severity(page, "Minor").click();
    await sendReport(page).dblclick();
    await expect(page.getByText(/Thank you|Updated/)).toBeVisible();
    expect(sent.count()).toBe(1);
  });

  test("[PORT-14] if the server fails the message is readable and the form is kept", async ({ page }) => {
    await open(page, "/pantry");
    await failRequests(page, /shortage-reports$/);
    await category(page, "Produce").click();
    await severity(page, "Serious").click();
    await note(page).fill("keep me");
    await sendReport(page).click();
    await expect(page.getByRole("alert").filter({ hasText: /could not do that/ })).toBeVisible();
    await expect(note(page)).toHaveValue("keep me");
  });

  test("[PORT-15] the page fits the screen and every control is tappable", async ({ page }) => {
    await open(page, "/pantry");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    const small = await page.evaluate(() =>
      [...document.querySelectorAll("main button, main input, main textarea, main summary")]
        .filter((e) => e.getBoundingClientRect().height > 0 && e.getBoundingClientRect().height < 43.5)
        .map((e) => (e as HTMLElement).innerText || (e as HTMLInputElement).id),
    );
    if ((page.viewportSize()?.width ?? 1280) < 1024) expect(small).toEqual([]);
  });

  test("[PORT-16] staff cannot use the portal API", async () => {
    for (const role of ["coordinator", "admin"] as const) {
      const api = await staffApi(role);
      expect((await api.get("/api/pantry/deliveries")).status()).toBe(403);
      expect((await api.post("/api/pantry/shortage-reports", { data: { category: "dairy", severity: 1 } })).status()).toBe(403);
    }
  });
});

test.describe("dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "admin");
  });

  test("[DASH-01][DASH-02][DASH-03][DASH-12] the dashboard shows figures, a clock, charts and the category table", async ({ page }) => {
    await open(page, "/admin/dashboard");
    await expect(page.getByRole("heading", { name: "Impact dashboard" })).toBeVisible();
    for (const label of ["Perishable spoilage", "Pantry-weeks with a shortage", "Pounds distributed", "Households served"]) {
      await expect(page.locator("dt", { hasText: label })).toBeVisible();
    }
    const clock = page.locator("main p", { hasText: /\d{4}.*\d:\d\d:\d\d/ }).first();
    const t1 = await clock.innerText();
    await page.waitForTimeout(2200);
    expect(await clock.innerText()).not.toBe(t1);
    await expect(page.locator(".recharts-wrapper")).toHaveCount(5);
    await expect(page.getByRole("row")).toHaveCount(9);
  });

  test("[DASH-04][DASH-05] changing the dates or pressing a preset changes the figures", async ({ page }) => {
    await open(page, "/admin/dashboard");
    const pounds = page.locator("dt", { hasText: "Pounds distributed" }).locator("xpath=following-sibling::dd");
    const before = await pounds.innerText();
    await page.getByRole("button", { name: "Last 12 weeks" }).click();
    await expect(pounds).not.toHaveText(before);
    const twelve = await pounds.innerText();
    await page.getByLabel("From").fill("2026-09-07");
    await expect(pounds).not.toHaveText(twelve);
    for (const preset of ["Last 26 weeks", "Last 52 weeks", "All data"]) await page.getByRole("button", { name: preset }).click();
    await expect(page.getByLabel("From")).toHaveValue(/^\d{4}-\d\d-\d\d$/);
  });

  test("[DASH-06][DASH-07] a start after the end, or more than 260 weeks, is explained", async ({ page }) => {
    await open(page, "/admin/dashboard");
    const sent = countRequests(page, "GET", /\/api\/dashboard\/metrics/);
    await page.getByLabel("From").fill("2026-09-28");
    await page.getByLabel("To").fill("2026-09-07");
    await expect(page.getByText("The start date must not be after the end date.")).toBeVisible();
    await page.getByLabel("To").fill("2026-09-28");
    await page.getByLabel("From").fill("2020-01-06");
    await expect(page.getByText(/at most 260 weeks/)).toBeVisible();
    expect(sent.count()).toBeLessThanOrEqual(2);
  });

  test("[DASH-08] dates outside 2020 to 2100 show an inline message and send nothing", async ({ page }) => {
    await open(page, "/admin/dashboard");
    const sent = countRequests(page, "GET", /\/api\/dashboard\/metrics/);
    await page.getByLabel("To").fill("9999-12-31");
    await page.getByLabel("From").fill("9999-12-01");
    await expect(page.getByText("Dates must be between 2020 and 2100.")).toBeVisible();
    await page.getByLabel("From").fill("1999-01-01");
    await expect(page.getByText("Dates must be between 2020 and 2100.")).toBeVisible();
    expect(sent.count()).toBe(0);
    await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
  });

  test("[DASH-08][DASH-09][DASH-10] far-past dates and a cleared date do not break the page", async ({ page }) => {
    await open(page, "/admin/dashboard");
    await page.getByLabel("From").fill("2020-01-06");
    await page.getByLabel("To").fill("2020-02-03");
    await expect(page.getByText(/No distributions, shortage reports or lots/)).toBeVisible();
    await page.getByLabel("From").fill("");
    await expect(page.getByRole("heading", { name: "Impact dashboard" })).toBeVisible();
    await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
  });

  test("[DASH-11] if the figures cannot be loaded the error is readable with Try again", async ({ page }) => {
    await open(page, "/admin/dashboard");
    await failRequests(page, /\/api\/dashboard\/metrics/);
    await page.getByRole("button", { name: "Last 12 weeks" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /could not do that/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("[DASH-13] a coordinator is sent away from the dashboard", async ({ page }) => {
    await page.context().clearCookies();
    await login(page, "coordinator");
    await page.goto("/admin/dashboard");
    await expect(page).toHaveURL(/\/coordinator$/);
    expect((await (await staffApi("coordinator")).get("/api/dashboard/metrics")).status()).toBe(403);
  });
});

test.describe("monthly summary", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    await page.locator("#month").waitFor();
  });
  const box = (page: Page) => page.getByLabel("Summary text");
  const draft = (page: Page) => page.getByRole("button", { name: /^Draft/ });

  test("[SUM-01][SUM-02] the month select lists months and there is no summary yet", async ({ page }) => {
    const options = await page.locator("#month").locator("option").allInnerTexts();
    expect(options.length).toBeGreaterThan(6);
    expect(options[0]).toMatch(/2026/);
    await expect(page.getByText(/No summary for .* yet/)).toBeVisible();
    await expect(draft(page)).toHaveText("Draft with AI");
  });

  test("[SUM-03][SUM-04] Draft with AI fills the box, and drafting again replaces it", async ({ page }) => {
    await draft(page).click();
    await expect(box(page)).toHaveValue(/distributed [\d,]+ pounds/, { timeout: 20_000 });
    await expect(draft(page)).toHaveText("Draft again with AI");
    await draft(page).click();
    await expect(box(page)).toHaveValue(/pounds/);
  });

  test("[SUM-05] the text can be edited up to 4,000 characters, in any script", async ({ page }) => {
    await box(page).fill(WEIRD.long + WEIRD.long);
    expect((await box(page).inputValue()).length).toBeLessThanOrEqual(4000);
    await box(page).fill(`${WEIRD.emoji} ${WEIRD.nonLatin} ${WEIRD.html}`);
    await expect(box(page)).toHaveValue(new RegExp("🥕"));
  });

  test("[SUM-06][SUM-13] approving saves it as final and locks the box", async ({ page }) => {
    await draft(page).click();
    await expect(box(page)).toHaveValue(/pounds/, { timeout: 20_000 });
    await box(page).fill(`Approved text ${WEIRD.emoji} ${WEIRD.nonLatin}`);
    await page.getByRole("button", { name: "Approve as final" }).click();
    await expect(page.getByText(/Approved and final/)).toBeVisible();
    await expect(box(page)).toHaveAttribute("readonly", "");
    await expect(page.getByRole("button", { name: "Approve as final" })).toHaveCount(0);
    await expect(draft(page)).toHaveCount(0);
  });

  test("[SUM-07] approving with no text is refused", async ({ page }) => {
    await box(page).fill(WEIRD.spaces);
    await page.getByRole("button", { name: "Approve as final" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /Write the summary text/ })).toBeVisible();
    await box(page).fill("");
    await page.getByRole("button", { name: "Approve as final" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /Write the summary text/ })).toBeVisible();
  });

  test("[SUM-08] a draft with an invented number is refused and offers a retry", async ({ page }) => {
    await setAi("bad_numbers");
    await draft(page).click();
    await expect(page.getByRole("alert").filter({ hasText: /not in the data/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Try the AI again" })).toBeVisible();
    await expect(box(page)).toHaveValue("");
    await setAi("ok");
    await page.getByRole("button", { name: "Try the AI again" }).click();
    await expect(box(page)).toHaveValue(/pounds/, { timeout: 20_000 });
  });

  test("[SUM-09] with the AI off the admin can still write and approve", async ({ page }) => {
    await setAi("down");
    await draft(page).click();
    await expect(page.getByRole("alert").first()).toBeVisible({ timeout: 20_000 });
    await box(page).fill("Written by hand.");
    await page.getByRole("button", { name: "Approve as final" }).click();
    await expect(page.getByText(/Approved and final/)).toBeVisible();
  });

  test("[SUM-10][SUM-11] an approved month stays final and each month shows its own summary", async ({ page }) => {
    await box(page).fill("September words.");
    await page.getByRole("button", { name: "Approve as final" }).click();
    await expect(page.getByText(/Approved and final/)).toBeVisible();
    const months = page.locator("#month");
    const first = await months.inputValue();
    await months.selectOption({ index: 1 });
    await expect(box(page)).toHaveValue("");
    await months.selectOption(first);
    await expect(box(page)).toHaveValue("September words.");
    await expect(draft(page)).toHaveCount(0);
  });

  test("[SUM-12] a coordinator or manager cannot draft or approve", async () => {
    for (const role of ["coordinator", "manager"] as const) {
      const api = await staffApi(role);
      expect((await api.post("/api/dashboard/summaries/2026-09/draft")).status()).toBe(403);
      expect((await api.post("/api/dashboard/summaries/2026-09/approve", { data: { text: "x" } })).status()).toBe(403);
    }
  });
});

test.describe("weekly refresh", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "admin");
    await open(page, "/admin/dashboard");
  });

  test("[REF-01][REF-03] Run weekly refresh shows progress then a result, with one request per double-click", async ({ page }) => {
    const sent = countRequests(page, "POST", /weekly-refresh$/);
    await page.getByRole("button", { name: "Run weekly refresh" }).dblclick();
    await expect(page.getByText(/Done in [\d.]+ s: forecast for the week of Oct 5/)).toBeVisible({ timeout: 60_000 });
    expect(sent.count()).toBe(1);
  });

  test("[REF-02] a failed refresh shows a readable message", async ({ page }) => {
    await failRequests(page, /weekly-refresh$/, 422, "refresh_partial");
    await page.getByRole("button", { name: "Run weekly refresh" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /could not do that/ })).toBeVisible();
  });

  test("[REF-04] a coordinator or manager cannot run the job", async () => {
    for (const role of ["coordinator", "manager"] as const) {
      expect((await (await staffApi(role)).post("/api/admin/jobs/weekly-refresh")).status()).toBe(403);
    }
  });
});
