import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { approveFor, expect, login, open, prepareAllocation, prepareForecast, type Role, setAi, staffApi, test } from "./fixtures";

// Accessibility scans. Every scan FAILS the run on any violation of the WCAG 2.0/2.1 A and AA rules
// (wcag2a, wcag2aa, wcag21a, wcag21aa). axe's extra "best practice" rules are recorded as advisory
// findings in the same report and do not fail the run. Results are written to test-results/a11y/*.json
// and summarised in docs/testing/a11y-report.md by `make e2e-report`.
const OUT = path.join(process.cwd(), "test-results", "a11y");
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

type Page = import("@playwright/test").Page;

type Found = { rule: string; impact: string; help: string; nodes: number; example: string; gated: boolean };

async function scan(page: Page, id: string, role: string, url: string, project: string) {
  const results = await new AxeBuilder({ page }).withTags([...WCAG, "best-practice"]).analyze();
  const violations: Found[] = results.violations.map((v) => ({
    rule: v.id,
    impact: v.impact ?? "minor",
    help: v.help,
    nodes: v.nodes.length,
    example: v.nodes[0]?.html.slice(0, 160) ?? "",
    gated: v.tags.some((t) => WCAG.includes(t)),
  }));
  mkdirSync(OUT, { recursive: true });
  writeFileSync(
    path.join(OUT, `${project}__${id}__${role}__${url.replace(/[^a-z0-9]+/gi, "_")}.json`),
    JSON.stringify({ id, role, url, project, violations }, null, 2),
  );
  const gated = violations.filter((v) => v.gated);
  expect(
    gated.map((v) => `${v.rule} (${v.impact}, ${v.nodes} element${v.nodes === 1 ? "" : "s"}): ${v.help} e.g. ${v.example}`),
    `WCAG violations on ${url}`,
  ).toEqual([]);
}

test.describe("accessibility scans", () => {
  test("[A11Y-01] login page", async ({ page }, info) => {
    await open(page, "/login");
    await scan(page, "A11Y-01", "Logged out", "/login", info.project.name);
  });

  const staff: [string, Role, string, string][] = [
    ["A11Y-02", "coordinator", "/coordinator", "/coordinator"],
    ["A11Y-03", "coordinator", "/coordinator/donations", "/coordinator/donations"],
    ["A11Y-05", "coordinator", "/coordinator/forecasts", "/coordinator/forecasts"],
    ["A11Y-07", "admin", "/admin/dashboard", "/admin/dashboard"],
    ["A11Y-09", "coordinator", "/does-not-exist-page", "/coordinator/donations/99999999"],
    // an admin can do everything a coordinator can: the same pages, scanned as that role
    ["A11Y-10", "admin", "/coordinator", "/coordinator"],
    ["A11Y-10", "admin", "/coordinator/donations", "/coordinator/donations"],
    ["A11Y-10", "admin", "/coordinator/forecasts", "/coordinator/forecasts"],
    ["A11Y-10", "admin", "/coordinator/allocations", "/coordinator/allocations"],
  ];
  for (const [id, role, label, url] of staff) {
    test(`[${id}] ${label} as ${role}`, async ({ page }, info) => {
      await login(page, role);
      if (id === "A11Y-05" || label.includes("forecasts")) await (await staffApi()).post("/api/forecasts/run");
      await open(page, url);
      await scan(page, id, role, label, info.project.name);
    });
  }

  test("[A11Y-04] donation review page", async ({ page }, info) => {
    await login(page, "coordinator");
    const api = await staffApi();
    const res = await api.post("/api/donations", { multipart: { file: { name: "m.eml", mimeType: "message/rfc822", buffer: Buffer.from("10 cases lettuce") } } });
    const id = (await res.json()).id;
    await open(page, `/coordinator/donations/${id}`);
    await scan(page, "A11Y-04", "coordinator", "/coordinator/donations/[id]", info.project.name);
  });

  test("[A11Y-06] allocations page with proposals", async ({ page }, info) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await scan(page, "A11Y-06", "coordinator", "/coordinator/allocations", info.project.name);
  });

  test("[A11Y-08] pantry portal", async ({ page }, info) => {
    const api = await prepareAllocation();
    await approveFor(api, 14, 2);
    await login(page, "manager");
    await open(page, "/pantry");
    await scan(page, "A11Y-08", "manager", "/pantry", info.project.name);
  });
});

// The same pages in the states a person actually reaches: errors showing, dialogs open, tables open,
// forms with a choice made. A page can pass at rest and fail here.
test.describe("accessibility scans of page states", () => {
  test("[A11Y-11] login with errors showing", async ({ page }, info) => {
    await open(page, "/login");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    await scan(page, "A11Y-11", "Logged out", "/login (errors)", info.project.name);
    await page.getByLabel("Email").fill("someone@example.org");
    await page.getByLabel("Password").fill("wrong-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /incorrect/i })).toBeVisible();
    await scan(page, "A11Y-11", "Logged out", "/login (wrong password)", info.project.name);
  });

  test("[A11Y-12] allocations: edit form, all tabs and the approve-all dialog", async ({ page }, info) => {
    await login(page, "coordinator");
    await prepareAllocation();
    await open(page, "/coordinator/allocations");
    await page.getByRole("button", { name: "Edit" }).first().click();
    await page.getByLabel("New amount (lb)").fill("0");
    await page.getByLabel("New amount (lb)").blur();
    await scan(page, "A11Y-12", "coordinator", "/coordinator/allocations (edit form with an error)", info.project.name);
    await page.getByRole("button", { name: "Cancel" }).first().click();
    await page.getByRole("button", { name: /^Approve all shown/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await scan(page, "A11Y-12", "coordinator", "/coordinator/allocations (dialog open)", info.project.name);
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: "All", exact: true }).click();
    await scan(page, "A11Y-12", "coordinator", "/coordinator/allocations (All tab)", info.project.name);
  });

  test("[A11Y-13] donation review: errors showing and the reject dialog", async ({ page }, info) => {
    await login(page, "coordinator");
    const api = await staffApi();
    const res = await api.post("/api/donations", { multipart: { file: { name: "m.eml", mimeType: "message/rfc822", buffer: Buffer.from("10 cases lettuce") } } });
    const id = (await res.json()).id;
    await open(page, `/coordinator/donations/${id}`);
    await page.getByLabel("Donor", { exact: true }).selectOption({ label: "Choose a donor…" });
    await page.getByRole("button", { name: /^Confirm and add/ }).click();
    await expect(page.getByText("Choose a donor, or add a new one.")).toBeVisible();
    await scan(page, "A11Y-13", "coordinator", "/coordinator/donations/[id] (errors)", info.project.name);
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await scan(page, "A11Y-13", "coordinator", "/coordinator/donations/[id] (reject dialog)", info.project.name);
  });

  test("[A11Y-14] forecasts with the table view open, and the dashboard with every table open", async ({ page }, info) => {
    await login(page, "coordinator");
    await prepareForecast();
    await open(page, "/coordinator/forecasts");
    await page.getByRole("button", { name: /view as table/i }).first().click();
    await scan(page, "A11Y-14", "coordinator", "/coordinator/forecasts (table view)", info.project.name);
    await login(page, "admin");
    await open(page, "/admin/dashboard");
    const toggles = page.getByRole("button", { name: /view as table/i });
    for (let i = (await toggles.count()) - 1; i >= 0; i--) await toggles.nth(i).click();
    await scan(page, "A11Y-14", "admin", "/admin/dashboard (table views)", info.project.name);
  });

  test("[A11Y-15] pantry portal: a report with errors, then with choices made", async ({ page }, info) => {
    const api = await prepareAllocation();
    await approveFor(api, 14, 2);
    await login(page, "manager");
    await open(page, "/pantry");
    await page.getByRole("button", { name: "Send report" }).click();
    await expect(page.getByRole("alert").first()).toBeVisible();
    await scan(page, "A11Y-15", "manager", "/pantry (report with errors)", info.project.name);
    await page.getByRole("button", { name: /^Dairy/ }).click();
    await page.getByRole("button", { name: /^Serious/ }).click();
    await scan(page, "A11Y-15", "manager", "/pantry (choices made)", info.project.name);
  });

  test("[A11Y-16] the unavailable page, the logged-out 404 and the AI-down message", async ({ page }, info) => {
    await open(page, "/unavailable");
    await scan(page, "A11Y-16", "Logged out", "/unavailable", info.project.name);
    await open(page, "/no-such-page-at-all");
    await scan(page, "A11Y-16", "Logged out", "/no-such-page", info.project.name);
    await setAi("down");
    await login(page, "coordinator");
    await open(page, "/coordinator/donations");
    await scan(page, "A11Y-16", "coordinator", "/coordinator/donations (AI down)", info.project.name);
  });
});
