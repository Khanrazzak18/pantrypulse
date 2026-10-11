import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { approveFor, login, open, prepareAllocation, type Role, staffApi, test } from "./fixtures";

// Accessibility scans. They REPORT violations (written to test-results/a11y/*.json and summarised in
// docs/testing/a11y-report.md by `make e2e-report`); they never fail the run. Fixing comes later.
const OUT = path.join(process.cwd(), "test-results", "a11y");

async function scan(page: import("@playwright/test").Page, id: string, role: string, url: string, project: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]).analyze();
  mkdirSync(OUT, { recursive: true });
  const violations = results.violations.map((v) => ({
    rule: v.id,
    impact: v.impact ?? "minor",
    help: v.help,
    nodes: v.nodes.length,
    example: v.nodes[0]?.html.slice(0, 160) ?? "",
  }));
  writeFileSync(
    path.join(OUT, `${project}__${id}__${role}.json`),
    JSON.stringify({ id, role, url, project, violations }, null, 2),
  );
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
  ];
  for (const [id, role, label, url] of staff) {
    test(`[${id}] ${label} as ${role}`, async ({ page }, info) => {
      await login(page, role);
      if (id === "A11Y-05") await (await staffApi()).post("/api/forecasts/run");
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
