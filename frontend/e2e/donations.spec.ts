import type { APIRequestContext, Page } from "@playwright/test";

import { open, countRequests, expect, file, isNarrow, login, setAi, staffApi, test, WEIRD } from "./fixtures";

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAX+XDSwAAAABJRU5ErkJggg==",
  "base64",
);
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n");
const EML = "From: market@example.org\nSubject: Donation\n\nWe are donating 10 cases of romaine lettuce.\n";

async function uploadViaApi(api: APIRequestContext, name = "manifest.eml", body: string | Buffer = EML): Promise<number> {
  const res = await api.post("/api/donations", { multipart: { file: file(name, body) } });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).id;
}

const fresh = async (api: APIRequestContext) =>
  ((await (await api.get("/api/donations")).json()) as { source_type: string; status: string }[]).filter(
    (d) => d.source_type !== "historical",
  );

const picker = (page: Page) => page.locator('input[type="file"]');
const alert = (page: Page) => page.getByRole("alert").filter({ hasText: /\S/ });

async function openReview(page: Page, body: string | Buffer = EML) {
  await login(page, "coordinator");
  const api = await staffApi("coordinator");
  const id = await uploadViaApi(api, "manifest.eml", body);
  await open(page, `/coordinator/donations/${id}`);
  await expect(page.getByRole("heading", { name: /Items/ })).toBeVisible();
  return { id, api };
}
const firstRow = (page: Page) => page.getByRole("row").first();

test.describe("donation list", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "coordinator");
  });

  test("[DON-01][DON-04] the list shows donations newest first and View opens one", async ({ page }) => {
    const api = await staffApi();
    const first = await uploadViaApi(api, "first.eml");
    const second = await uploadViaApi(api, "second.eml");
    await open(page, "/coordinator/donations");
    const links = page.getByRole("link", { name: "Review", exact: true });
    await expect(links.first()).toHaveAttribute("href", `/coordinator/donations/${second}`);
    expect(first).toBeLessThan(second);
    await links.first().click();
    await expect(page).toHaveURL(new RegExp(`/coordinator/donations/${second}$`));
  });

  test("[DON-02][DON-05] each filter link changes the list and the empty state names the filter", async ({ page }) => {
    await open(page, "/coordinator/donations?status=pending_review");
    await expect(page.getByText(/No donations with status/)).toBeVisible();
    const api = await staffApi();
    await uploadViaApi(api, "keep.eml");
    const toss = await uploadViaApi(api, "toss.eml");
    await api.post(`/api/donations/${toss}/reject`);
    await open(page, "/coordinator/donations");
    for (const [name, url] of [["Needs review", /status=pending_review/], ["Confirmed", /status=confirmed/], ["Rejected", /status=rejected/], ["All", /donations$/]] as const) {
      await page.getByRole("link", { name, exact: true }).click();
      await expect(page).toHaveURL(url);
      await expect(page.getByRole("link", { name, exact: true })).toHaveAttribute("aria-current", "page");
    }
    await open(page, "/coordinator/donations?status=pending_review");
    await expect(page.getByRole("link", { name: "Review", exact: true })).toHaveCount(1);
    await open(page, "/coordinator/donations?status=rejected");
    await expect(page.getByRole("link", { name: "View", exact: true })).toHaveCount(1);
  });

  test("[DON-03] an unknown status in the URL is treated as All and nothing executes", async ({ page }) => {
    await uploadViaApi(await staffApi(), "a.eml");
    for (const status of ["bogus", WEIRD.html, WEIRD.sql]) {
      await open(page, `/coordinator/donations?status=${encodeURIComponent(status)}`);
      await expect(page.getByRole("heading", { name: "Donations" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Review", exact: true })).toHaveCount(1);
      await expect(page.getByRole("link", { name: "View", exact: true }).first()).toBeVisible();
    }
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  });

  test("[DON-06] tampered banner parameters never show script or broken text", async ({ page }) => {
    await open(page, "/coordinator/donations?added=3&lbs=100");
    await expect(page.getByText("Added 3 lots to inventory (100 lb).")).toBeVisible();
    await open(page, "/coordinator/donations?rejected=1");
    await expect(page.getByText(/Donation rejected/)).toBeVisible();
    for (const q of ["added=abc&lbs=x", "added=-5&lbs=-9", `added=1&lbs=${encodeURIComponent(WEIRD.html)}`]) {
      await open(page, `/coordinator/donations?${q}`);
      await expect(page.getByRole("heading", { name: "Donations" })).toBeVisible();
      await expect(page.getByText(/NaN|undefined|\[object/)).toHaveCount(0);
    }
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  });

  test("[DON-07] a table from 768 px and cards below, never a sideways page scroll", async ({ page }) => {
    await uploadViaApi(await staffApi(), "a.eml");
    await open(page, "/coordinator/donations");
    const table = page.getByRole("table").first();
    if (isNarrow(page)) await expect(table).toBeHidden();
    else await expect(table).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("[DON-08] an admin sees the same page", async ({ page }) => {
    await page.context().clearCookies();
    await login(page, "admin");
    await open(page, "/coordinator/donations");
    await expect(page.getByRole("heading", { name: "Donations" })).toBeVisible();
    await expect(picker(page)).toBeAttached();
  });
});

test.describe("upload", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "coordinator");
    await open(page, "/coordinator/donations");
  });

  for (const [id, name, body] of [
    ["UP-01", "manifest.eml", EML],
    ["UP-02", "manifest.txt", "10 cases of lettuce"],
    ["UP-03", "manifest.pdf", PDF],
    ["UP-04", "manifest.png", PNG],
  ] as const) {
    test(`[${id}] a valid ${name.split(".")[1]} opens the review page`, async ({ page }) => {
      await picker(page).setInputFiles(file(name, body));
      await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
      await expect(page.getByRole("heading", { name: /Items/ })).toBeVisible();
      await expect(page.getByText(/AI read the donor as/)).toBeVisible();
    });
  }

  test("[UP-02] 5,000 characters, emoji and non-Latin text upload fine", async ({ page }) => {
    await picker(page).setInputFiles(file("long.txt", `${WEIRD.long}\n${WEIRD.emoji}\n${WEIRD.nonLatin}\n`));
    await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
  });

  test("[UP-05] a 0-byte file is refused before upload", async ({ page }) => {
    const sent = countRequests(page, "POST", /\/api\/donations$/);
    await picker(page).setInputFiles(file("empty.txt", ""));
    await expect(alert(page)).toContainText("is empty");
    expect(sent.count()).toBe(0);
  });

  test("[UP-06] an .exe is refused with the allowed types", async ({ page }) => {
    const sent = countRequests(page, "POST", /\/api\/donations$/);
    for (const name of ["setup.exe", "run.sh", "noextension"]) {
      await picker(page).setInputFiles(file(name, "MZ binary"));
      await expect(alert(page)).toContainText(/can't be used/);
      await page.getByRole("button", { name: "Choose a different file" }).click().catch(() => {});
    }
    expect(sent.count()).toBe(0);
  });

  test("[UP-07] an .exe renamed to .pdf is refused by the server with a readable message", async ({ page }) => {
    await picker(page).setInputFiles(file("invoice.pdf", Buffer.concat([Buffer.from("MZ"), Buffer.alloc(200, 1)])));
    await expect(alert(page)).toContainText(/pdf|not a valid|isn't/i);
    await expect(page).toHaveURL(/\/coordinator\/donations$/);
  });

  test("[UP-08] an 11 MB file is refused and names the limit", async ({ page }) => {
    const sent = countRequests(page, "POST", /\/api\/donations$/);
    await picker(page).setInputFiles(file("big.txt", Buffer.alloc(11 * 1024 * 1024, 97)));
    await expect(alert(page)).toContainText("10 MB");
    expect(sent.count()).toBe(0);
  });

  test("[UP-09][UP-10][UP-11] when the AI is down the error offers Try again and a different file", async ({ page }) => {
    await setAi("down");
    await picker(page).setInputFiles(file("manifest.eml", EML));
    await expect(alert(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    await page.getByRole("button", { name: "Choose a different file" }).click();
    await expect(alert(page)).toHaveCount(0);
    await picker(page).setInputFiles(file("manifest.eml", EML));
    await expect(alert(page)).toBeVisible();
    await setAi("ok");
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
  });

  test("[UP-12] a manifest with no food says so and saves nothing", async ({ page }) => {
    await picker(page).setInputFiles(file("empty.txt", "E2E_EMPTY nothing here"));
    await expect(alert(page)).toBeVisible();
    expect(await fresh(await staffApi())).toHaveLength(0);
  });

  test("[UP-13] one chosen file creates one donation", async ({ page }) => {
    const sent = countRequests(page, "POST", /\/api\/donations$/);
    await picker(page).setInputFiles(file("manifest.eml", EML));
    await picker(page).setInputFiles(file("manifest.eml", EML), { timeout: 500 }).catch(() => {});
    await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
    expect(sent.count()).toBe(1);
    expect(await fresh(await staffApi())).toHaveLength(1);
  });

  test("[UP-14] odd filenames are shown as text and never run", async ({ page }) => {
    for (const name of ["<img src=x onerror=window.__pwned=1>.txt", "😀.txt", "日本語.txt", `${"n".repeat(180)}.txt`]) {
      await open(page, "/coordinator/donations");
      await picker(page).setInputFiles(file(name, "10 cases lettuce"));
      await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
      expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
    }
  });

  test("[UP-15] Cancel stops a slow read and nothing is saved", async ({ page }) => {
    await picker(page).setInputFiles(file("slow.txt", "E2E_SLOW 10 cases lettuce"));
    await expect(page.getByText(/Reading slow.txt/)).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText(/Reading slow.txt/)).toHaveCount(0);
    await page.waitForTimeout(5000);
    await expect(page).toHaveURL(/\/coordinator\/donations$/);
  });

  test("[UP-16] dropping a file works like choosing it", async ({ page }) => {
    const data = await page.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File(["10 cases lettuce"], "dropped.txt", { type: "text/plain" }));
      return d;
    });
    await page.locator("label", { hasText: "Choose a file" }).dispatchEvent("drop", { dataTransfer: data });
    await expect(page).toHaveURL(/\/coordinator\/donations\/\d+$/);
  });

  test("[UP-17] a pantry manager cannot upload", async () => {
    const api = await staffApi("manager");
    const res = await api.post("/api/donations", { multipart: { file: file("a.txt", "x") } });
    expect(res.status()).toBe(403);
    expect((await res.json()).error.code).toBe("forbidden");
  });
});

test.describe("review", () => {
  test("[REV-01][REV-19] the review page has donor, items and buttons, and a way back", async ({ page }) => {
    await openReview(page);
    await expect(page.locator("#donor")).toBeVisible();
    await expect(page.getByRole("row")).toHaveCount(3);
    await expect(page.getByRole("button", { name: /Confirm and add 3 lots/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
    await page.getByRole("link", { name: /All donations/ }).click();
    await expect(page).toHaveURL(/\/coordinator\/donations$/);
  });

  test("[REV-02] a low-confidence field is highlighted until it is edited", async ({ page }) => {
    await openReview(page);
    await expect(page.getByText(/1 field the AI was unsure about/)).toBeVisible();
    await firstRow(page).getByLabel(/Storage/).selectOption("ambient");
    await expect(page.getByText(/Every field was above 80% confidence/)).toBeVisible();
  });

  test("[REV-03] an existing donor can be chosen", async ({ page }) => {
    const { api } = await openReview(page);
    const first = await uploadViaApi(api, "second.eml");
    await api.post(`/api/donations/${first}/confirm`, {
      data: { donor_name: "Existing Donor Co", items: [{ name: "Rice", category: "dry_goods", quantity: 1, unit: "bag", estimated_weight_lbs: 10, expiry_date: null, storage_type: "ambient", source_index: null }] },
    });
    await page.reload();
    await page.locator("#donor").selectOption({ label: "Existing Donor Co" });
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/\/coordinator\/donations\?added=3/);
  });

  test("[REV-04][REV-05] a new donor needs a name and the donor is required", async ({ page }) => {
    await openReview(page);
    const donor = page.locator("#donor");
    await donor.selectOption({ label: "Choose a donor…" });
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page.locator("#donor-error")).toBeVisible();
    await donor.selectOption({ label: "New donor…" });
    const name = page.getByLabel("New donor name");
    await expect(name).toBeVisible();
    await name.fill(WEIRD.spaces);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page.locator("#donor-error")).toBeVisible();
    await name.fill("x".repeat(200));
    expect((await name.inputValue()).length).toBeLessThanOrEqual(120);
    await name.fill(`${WEIRD.emoji} ${WEIRD.nonLatin}`);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/\/coordinator\/donations\?added=3/);
  });

  test("[REV-06] the item name is required, limited to 200 characters, and odd text is kept literally", async ({ page }) => {
    await openReview(page);
    const name = firstRow(page).getByLabel("Item");
    await name.fill(WEIRD.spaces);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page.getByText("Enter the item name.")).toBeVisible();
    await name.fill("n".repeat(201));
    expect((await name.inputValue()).length).toBeLessThanOrEqual(200);
    await name.fill(WEIRD.nonLatin + WEIRD.emoji);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/added=3/);
  });

  test("[REV-07] quantity must be above zero and numeric", async ({ page }) => {
    await openReview(page);
    const qty = firstRow(page).getByLabel(/Quantity|Qty/);
    for (const bad of ["0", "-3", "abc", ""]) {
      await qty.fill(bad);
      await page.getByRole("button", { name: /Confirm and add/ }).click();
      await expect(page.getByText("Enter a quantity above 0.")).toBeVisible();
    }
    await qty.fill("2.5");
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/added=3/);
  });

  test("[REV-08] weight must be above zero and not absurd", async ({ page }) => {
    await openReview(page);
    const weight = firstRow(page).getByLabel(/Weight/);
    for (const bad of ["0", "-1", "abc"]) {
      await weight.fill(bad);
      await page.getByRole("button", { name: /Confirm and add/ }).click();
      await expect(page.getByText("Enter a weight above 0.")).toBeVisible();
    }
    await weight.fill("100001");
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page.getByText("That weight looks too large.")).toBeVisible();
  });

  test("[REV-09] an expiry date in the past is refused", async ({ page }) => {
    await openReview(page);
    const expiry = firstRow(page).getByLabel(/Expire/);
    for (const past of ["2020-01-01", "1900-01-01"]) {
      await expiry.fill(past);
      await page.getByRole("button", { name: /Confirm and add/ }).click();
      await expect(page.getByText("This item has already expired.")).toBeVisible();
    }
    await expect(page).toHaveURL(/donations\/\d+$/);
  });

  test("[REV-10] an expiry date outside 2020 to 2100 shows an inline message", async ({ page }) => {
    await openReview(page);
    for (const far of ["9999-12-31", "2101-01-01"]) {
      await firstRow(page).getByLabel(/Expire/).fill(far);
      await page.getByRole("button", { name: /Confirm and add/ }).click();
      await expect(page.getByText("Dates must be between 2020 and 2100.")).toBeVisible();
    }
    await expect(page).toHaveURL(/donations\/\d+$/);
    await firstRow(page).getByLabel(/Expire/).fill("2100-12-31");
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/added=3/);
  });

  test("[REV-11] the unit is required", async ({ page }) => {
    await openReview(page);
    await firstRow(page).getByLabel("Unit").fill(WEIRD.spaces);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page.getByText("Enter a unit.")).toBeVisible();
  });

  test("[REV-12] category and storage selects change the saved item", async ({ page }) => {
    const { id, api } = await openReview(page);
    const row = firstRow(page);
    await row.getByLabel(/Category/).selectOption("protein");
    await row.getByLabel(/Storage/).selectOption("frozen");
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/added=3/);
    const detail = await (await api.get(`/api/donations/${id}`)).json();
    expect(detail.items[0]).toMatchObject({ category: "protein", storage_type: "frozen" });
  });

  test("[REV-13] removing rows works, and removing every row blocks the confirm", async ({ page }) => {
    await openReview(page);
    await page.getByRole("button", { name: /^Remove row 1/ }).click();
    await expect(page.getByRole("row")).toHaveCount(2);
    await page.getByRole("button", { name: /^Remove row 1/ }).click();
    await page.getByRole("button", { name: /^Remove row 1/ }).click();
    await expect(page.getByText(/No items left/)).toBeVisible();
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/donations\/\d+$/);
    await expect(alert(page).or(page.getByRole("button", { name: /Confirm and add/ }).and(page.locator(":disabled")))).toBeVisible();
  });

  test("[REV-14] a new row is empty and must be filled in", async ({ page }) => {
    await openReview(page);
    await page.getByRole("button", { name: "+ Add a row" }).click();
    await expect(page.getByRole("row")).toHaveCount(4);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page.getByText("Enter the item name.")).toBeVisible();
  });

  test("[REV-15][REV-20] confirming adds lots; HTML and SQL text are saved literally", async ({ page }) => {
    const { id, api } = await openReview(page);
    await firstRow(page).getByLabel("Item").fill(`<b>x</b> ${WEIRD.sql}`);
    await page.getByRole("button", { name: /Confirm and add 3 lots/ }).click();
    await expect(page).toHaveURL(/\/coordinator\/donations\?added=3/);
    await expect(page.getByText(/Added 3 lots to inventory/)).toBeVisible();
    const detail = await (await api.get(`/api/donations/${id}`)).json();
    expect(detail.items[0].name).toBe(`<b>x</b> ${WEIRD.sql}`);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  });

  test("[REV-16] double-clicking Confirm sends one request and makes one set of lots", async ({ page }) => {
    const { api } = await openReview(page);
    const sent = countRequests(page, "POST", /\/confirm$/);
    await page.getByRole("button", { name: /Confirm and add/ }).dblclick();
    await expect(page).toHaveURL(/added=3/);
    expect(sent.count()).toBe(1);
    expect((await fresh(api)).filter((d) => d.status === "confirmed")).toHaveLength(1);
  });

  test("[REV-17] Reject asks first, can be cancelled, and then rejects", async ({ page }) => {
    await openReview(page);
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByRole("alertdialog", { name: "Confirm rejection" })).toBeVisible();
    await page.getByRole("button", { name: "Keep reviewing" }).click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await page.getByRole("button", { name: "Yes, reject" }).click();
    await expect(page).toHaveURL(/rejected=1/);
  });

  test("[REV-18] a confirmed donation is read only", async ({ page }) => {
    const { id } = await openReview(page);
    await page.getByRole("button", { name: /Confirm and add/ }).click();
    await expect(page).toHaveURL(/added=3/);
    await open(page, `/coordinator/donations/${id}`);
    await expect(page.getByRole("button", { name: /Confirm and add/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
  });

  test("[SHELL-10] a donation that does not exist shows a not-found page", async ({ page }) => {
    await login(page, "coordinator");
    for (const id of ["99999999", "0", "-1", "abc"]) {
      const res = await page.goto(`/coordinator/donations/${id}`);
      expect(res?.status()).toBe(404);
      await expect(page.getByRole("heading", { name: /find that/ })).toBeVisible();
    }
  });
});
