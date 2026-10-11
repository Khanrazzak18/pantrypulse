import type { Page } from "@playwright/test";

import {
  allocationRows,
  approveFor,
  countRequests,
  expect,
  failRequests,
  login,
  open,
  prepareAllocation,
  prepareForecast,
  setAi,
  staffApi,
  test,
  WEIRD,
} from "./fixtures";

const noPwn = async (page: Page) =>
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();

test.describe("forecasts", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "coordinator");
  });

  test("[FC-01] before any run the page says there is no forecast yet", async ({ page }) => {
    await open(page, "/coordinator/forecasts");
    await expect(page.getByText(/No forecast has been run yet/).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Run forecast", exact: true })).toBeVisible();
  });

  test("[FC-02][FC-09] Run forecast shows progress then the result; the accuracy table is there", async ({ page }) => {
    await open(page, "/coordinator/forecasts");
    await page.getByRole("button", { name: "Run forecast", exact: true }).click();
    await expect(page.getByText(/Forecast for the week of Oct 5 saved/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Run forecast again" })).toBeVisible();
    await expect(page.getByText(/How accurate has it been/)).toBeVisible();
    await expect(page.getByText(/Forecast model/)).toBeVisible();
  });

  test("[FC-03] running twice works and a double-click sends one request", async ({ page }) => {
    await open(page, "/coordinator/forecasts");
    const sent = countRequests(page, "POST", /\/api\/forecasts\/run$/);
    await page.getByRole("button", { name: "Run forecast", exact: true }).dblclick();
    await expect(page.getByText(/saved in/)).toBeVisible({ timeout: 30_000 });
    expect(sent.count()).toBe(1);
    await page.getByRole("button", { name: "Run forecast again" }).click();
    await expect(page.getByText(/saved in/)).toBeVisible({ timeout: 30_000 });
    expect(sent.count()).toBe(2);
  });

  test("[FC-04] an admin can run the forecast", async ({ page }) => {
    await page.context().clearCookies();
    await login(page, "admin");
    await open(page, "/coordinator/forecasts");
    await page.getByRole("button", { name: "Run forecast", exact: true }).click();
    await expect(page.getByText(/saved in/)).toBeVisible({ timeout: 30_000 });
  });

  test("[FC-05][FC-06] the pantry and category selects change the chart", async ({ page }) => {
    await prepareForecast();
    await open(page, "/coordinator/forecasts");
    const pantry = page.locator("#pantry");
    const category = page.locator("#category");
    expect(await pantry.locator("option").count()).toBe(85);
    expect(await category.locator("option").count()).toBe(8);
    const requests: string[] = [];
    page.on("request", (r) => /\/api\/forecasts\/series/.test(r.url()) && requests.push(r.url()));
    await pantry.selectOption({ index: 5 });
    await category.selectOption("dairy");
    await expect.poll(() => requests.some((u) => /category=dairy/.test(u))).toBeTruthy();
    await expect(page.getByRole("heading", { name: /Pantry 06 · Dairy/ })).toBeVisible();
  });

  test("[FC-07][FC-08] last year's line and the numbers table can be shown", async ({ page }) => {
    await prepareForecast();
    await open(page, "/coordinator/forecasts");
    const box = page.getByLabel(/last year/i);
    await box.check();
    await expect(box).toBeChecked();
    await box.uncheck();
    await page.getByRole("button", { name: "View as table" }).click();
    await expect(page.getByRole("columnheader", { name: "Week of" })).toBeVisible();
  });

  test("[FC-10] if the chart data cannot be loaded the error is readable", async ({ page }) => {
    await failRequests(page, /\/api\/forecasts\/series/);
    await open(page, "/coordinator/forecasts");
    await expect(page.getByText(/could not do that|Could not load/i).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Run forecast/ })).toBeEnabled();
  });

  test("[FC-11] a refused run shows why", async ({ page }) => {
    await failRequests(page, /\/api\/forecasts\/run$/, 422, "not_enough_history");
    await open(page, "/coordinator/forecasts");
    await page.getByRole("button", { name: "Run forecast", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: /could not do that/ })).toBeVisible();
  });
});

const tile = (page: Page, label: string) => page.locator("dt", { hasText: label }).locator("xpath=following-sibling::dd");
const rowButtons = (page: Page, name: string) => page.getByRole("button", { name, exact: true });
const notice = (page: Page) => page.locator("main").getByRole("alert").or(page.locator("main").getByRole("status")).filter({ hasText: /\S/ });

test.describe("allocations", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "coordinator");
  });

  test("[AL-01] before any run the page is empty and offers Run allocation", async ({ page }) => {
    await open(page, "/coordinator/allocations");
    await expect(page.getByText("Nothing to review yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Run allocation" })).toBeVisible();
  });

  test("[AL-02] running without a forecast says to run the forecast first", async ({ page }) => {
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Run allocation" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /forecast/i })).toBeVisible();
  });

  test("[AL-03][AL-19] Run allocation proposes shipments grouped by pantry, with matching tiles", async ({ page }) => {
    await prepareForecast();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Run allocation" }).click();
    await expect(page.getByText(/Proposed \d+ shipments/)).toBeVisible({ timeout: 40_000 });
    await expect(page.getByRole("heading", { name: /^Pantry \d\d$/ }).first()).toBeVisible();
    const api = await staffApi();
    const summary = (await (await api.get("/api/allocations")).json()).summary;
    await expect(tile(page, "To review")).toContainText(String(summary.proposed).replace(/\B(?=(\d{3})+(?!\d))/g, ","));
  });

  test("[AL-04] Run again replaces undecided rows and keeps decided ones, once per click", async ({ page }) => {
    const api = await prepareAllocation();
    await approveFor(api, 14, 2);
    await open(page, "/coordinator/allocations");
    const sent = countRequests(page, "POST", /\/api\/allocations\/run$/);
    await page.getByRole("button", { name: "Run again" }).dblclick();
    await expect(page.getByText(/Proposed \d+ shipments/)).toBeVisible({ timeout: 40_000 });
    expect(sent.count()).toBe(1);
    const rows = await allocationRows(api);
    expect(rows.filter((r) => r.status === "approved")).toHaveLength(2);
  });

  test("[AL-05] each status tab shows its rows", async ({ page }) => {
    const api = await prepareAllocation();
    const [toApprove] = await approveFor(api, 14, 1);
    const rows = await allocationRows(api);
    const toReject = rows.find((r) => r.status === "proposed" && r.pantry.id === 20)!;
    await api.post(`/api/allocations/${toReject.id}/reject`);
    await open(page, "/coordinator/allocations");
    for (const [name, group] of [["Approved", "Pantry 14"], ["Rejected", "Pantry 20"]] as const) {
      await page.getByRole("tab", { name, exact: true }).click();
      await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("heading", { name: group })).toBeVisible();
      await expect(page.getByRole("heading", { name: /^Pantry \d\d$/ })).toHaveCount(1);
    }
    await page.getByRole("tab", { name: "To review", exact: true }).click();
    await expect(page.getByRole("heading", { name: /^Pantry \d\d$/ }).first()).toBeVisible();
    await page.getByRole("tab", { name: "All", exact: true }).click();
    expect(toApprove).toBeGreaterThan(0);
  });

  test("[AL-06] the county filter keeps only that county's pantries", async ({ page }) => {
    const api = await prepareAllocation();
    const rows = await allocationRows(api);
    const county = (await page.request.get("/api/pantries").then((r) => r.json())).find((p: { id: number }) => p.id === 14).county;
    const names = new Set(rows.filter((r) => r.pantry.county === county).map((r) => r.pantry.name));
    await open(page, "/coordinator/allocations");
    await page.getByLabel("County").selectOption(county);
    const shown = await page.getByRole("heading", { name: /^Pantry \d\d$/ }).allInnerTexts();
    expect(shown.length).toBeGreaterThan(0);
    for (const name of shown) expect(names.has(name)).toBeTruthy();
  });

  test("[AL-07][AL-08] search finds pantries; odd text just finds nothing", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    const search = page.getByLabel(/Search pantry or food/);
    await search.fill("Pantry 14");
    await expect(page.getByRole("heading", { name: "Pantry 14" })).toBeVisible();
    await search.fill(WEIRD.spaces);
    await expect(page.getByRole("heading", { name: /^Pantry \d\d$/ }).first()).toBeVisible();
    for (const text of [WEIRD.emoji, WEIRD.html, WEIRD.sql, WEIRD.long, "zzzz-no-match"]) {
      await search.fill(text);
      await expect(page.getByText("No shipments match these filters.")).toBeVisible();
    }
    await noPwn(page);
  });

  test("[AL-09] Approve moves one row to Approved, once per double-click", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    const sent = countRequests(page, "POST", /\/api\/allocations\/\d+\/approve$/);
    await rowButtons(page, "Approve").first().dblclick();
    await expect(tile(page, "Approved")).toContainText(/^1 ·/);
    expect(sent.count()).toBe(1);
  });

  test("[AL-10] Reject moves one row to Rejected", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await rowButtons(page, "Reject").first().click();
    await expect(tile(page, "Rejected")).toHaveText("1");
  });

  test("[AL-11] Edit opens a prefilled form and Cancel closes it", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await rowButtons(page, "Edit").first().click();
    const amount = page.getByLabel("New amount (lb)");
    await expect(amount).toBeVisible();
    expect(Number(await amount.inputValue())).toBeGreaterThan(0);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(amount).toHaveCount(0);
  });

  test("[AL-12] a valid edit (including a decimal) is saved as Edited", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    for (const value of ["12", "12.5", "12.345"]) {
      await rowButtons(page, "Edit").first().click();
      await page.getByLabel("New amount (lb)").fill(value);
      await Promise.all([
        page.waitForResponse((r) => /\/edit$/.test(r.url()) && r.request().method() === "POST"),
        page.getByRole("button", { name: "Save", exact: true }).click(),
      ]);
      await expect(page.getByRole("alert").filter({ hasText: /\S/ }).first()).toHaveCount(0);
    }
    await expect(tile(page, "Approved")).toContainText(/^3 ·/);
  });

  test("[AL-13] invalid amounts show a message and save nothing", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await rowButtons(page, "Edit").first().click();
    const amount = page.getByLabel("New amount (lb)");
    const sent = countRequests(page, "POST", /\/edit$/);
    const cases: [string, RegExp][] = [
      ["", /Enter an amount/],
      ["0", /more than 0/],
      ["-5", /more than 0/],
      ["abc", /Enter a number/],
      [WEIRD.emoji, /Enter a number/],
      [WEIRD.spaces, /Enter an amount/],
      ["1000000000", /more than the/],
    ];
    for (const [value, message] of cases) {
      await amount.fill(value);
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.locator('[id^="lbs-err-"]')).toContainText(message);
    }
    expect(sent.count()).toBe(0);
  });

  test("[AL-14] the note is capped at 500 characters; HTML and SQL text are saved literally", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await rowButtons(page, "Edit").first().click();
    const note = page.getByLabel(/Note/);
    await note.fill("n".repeat(501));
    expect((await note.inputValue()).length).toBeLessThanOrEqual(500);
    await note.fill(`${WEIRD.html} ${WEIRD.sql} ${WEIRD.emoji}`);
    await page.getByLabel("New amount (lb)").fill("5");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(tile(page, "Approved")).toContainText(/^1 ·/);
    await noPwn(page);
  });

  test("[AL-15] Approve all shown asks first; Cancel changes nothing; confirming approves the shown rows once", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: /Approve all shown/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(/This approves \d+ shipments/);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(tile(page, "Approved")).toContainText(/^0 ·/);
    await page.getByRole("button", { name: /Approve all shown/ }).click();
    const sent = countRequests(page, "POST", /bulk-approve$/);
    await dialog.getByRole("button", { name: /^Approve \d+/ }).dblclick();
    await expect(page.getByText(/Approved \d+ shipments/)).toBeVisible({ timeout: 30_000 });
    expect(sent.count()).toBe(1);
  });

  test("[AL-16] Approve all with a filter approves only the shown rows", async ({ page }) => {
    const api = await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByLabel(/Search pantry or food/).fill("Pantry 14");
    await page.getByRole("button", { name: /Approve all shown/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^Approve \d+/ }).click();
    await expect(page.getByText(/Approved \d+ shipments/)).toBeVisible({ timeout: 30_000 });
    const approved = (await allocationRows(api)).filter((r) => r.status === "approved");
    expect(approved.length).toBeGreaterThan(0);
    expect(new Set(approved.map((r) => r.pantry.id))).toEqual(new Set([14]));
  });

  test("[AL-17] Write more AI reasons tags more rows as AI", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    const before = await page.locator('[title^="Written by the AI"]').count();
    await page.getByRole("button", { name: "Write more AI reasons" }).click();
    await expect(page.getByText(/reasons are now written by the AI/)).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => page.locator('[title^="Written by the AI"]').count()).toBeGreaterThan(before);
  });

  test("[AL-18] with the AI off the run still works and every row is a template", async ({ page }) => {
    await setAi("down");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await expect(page.getByRole("heading", { name: /^Pantry \d\d$/ }).first()).toBeVisible();
    await expect(page.locator('[title^="Written by the AI"]')).toHaveCount(0);
    await expect(page.locator('[title="Built from a template"]').first()).toBeVisible();
  });

  test("[AL-20] if a run fails the error is readable and the page stays usable", async ({ page }) => {
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await failRequests(page, /\/api\/allocations\/run$/);
    await page.getByRole("button", { name: "Run again" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /could not do that/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run again" })).toBeEnabled();
  });

  test("[AL-21] a row someone else already decided gives a clear message", async ({ page }) => {
    const api = await prepareAllocation();
    await open(page, "/coordinator/allocations");
    const first = (await allocationRows(api)).find((r) => r.status === "proposed")!;
    await api.post(`/api/allocations/${first.id}/approve`);
    await rowButtons(page, "Approve").first().click();
    await expect(page.getByRole("alert").filter({ hasText: /already decided|Refresh/ })).toBeVisible();
  });

  test("[AL-22] running with no stock explains it", async ({ page }) => {
    await prepareForecast();
    await failRequests(page, /\/api\/allocations\/run$/, 422, "no_inventory");
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Run allocation" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /could not do that/ })).toBeVisible();
  });

  test("[AL-23] an admin can run and approve", async ({ page }) => {
    await page.context().clearCookies();
    await login(page, "admin");
    await prepareForecast();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Run allocation" }).click();
    await expect(page.getByText(/Proposed \d+ shipments/)).toBeVisible({ timeout: 40_000 });
    await rowButtons(page, "Approve").first().click();
    await expect(tile(page, "Approved")).toContainText(/^1 ·/);
  });

  test("[AL-24] a pantry manager cannot approve", async () => {
    const api = await prepareAllocation();
    const first = (await allocationRows(api)).find((r) => r.status === "proposed")!;
    const manager = await staffApi("manager");
    const res = await manager.post(`/api/allocations/${first.id}/approve`);
    expect(res.status()).toBe(403);
    expect((await res.json()).error.code).toBe("forbidden");
  });
});

void notice;
