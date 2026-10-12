# Bugs found and fixed in assignment 5.4 (Stages 10 to 13)

Found by the end-to-end tests (`make e2e`), by probing the API with out-of-range and odd input, and
(BUG-10) by hand, by stopping the database. **All ten are fixed.** Each has a regression test that was
written first and seen failing, and an end-to-end test (the `test.fail()` markers that proved the bugs
in Stage 10 were removed as each was fixed). The fuzz test `backend/tests/test_api_fuzz.py` now guards
the whole class of bug: it sends hostile ids, dates, numbers, long text and control characters to every
API route as a logged-out caller, a pantry manager and an admin, and fails on any HTTP 500.

Severity: **High** loses data, leaks data or blocks a main job; **Medium** shows a wrong or broken
result for input a real user can type; **Low** needs an unusual request or is cosmetic.

| ID | Severity | Where | Root cause | Fix | Regression tests |
| --- | --- | --- | --- | --- | --- |
| BUG-01 | Medium | `GET /api/donations/{id}`, `/api/pantries/{id}`, `POST /api/allocations/{id}/approve`, `/reject`, `/edit`, `/api/allocations/runs/{id}/reasons`, `/api/donations/{id}/confirm`, `/reject`; page `/coordinator/donations/{id}` returned 500 / "Something went wrong" for an id above 2,147,483,647 | Path ids were plain `int`, so a 20-digit id reached Postgres, whose integer column is 32-bit, and the database error was unhandled | Shared type `PathId` (1 to 2,147,483,647) on every path id; the validation handler turns an out-of-range path id into a **404 `not_found`** in the envelope (such a record cannot exist) | `test_bug_regressions.py::test_bug_01_*` (8 routes x 4 ids), E2E `[API-01]`, `[SHELL-10]` |
| BUG-02 | Low | `GET /api/forecasts/series?pantry_id=` and `GET /api/forecasts?pantry_id=` / `run_id=` returned 500 | Query ids were unbounded `int`, same cause as BUG-01 | Shared type `PositiveId` on every id in a query string: **422** with a field message | `test_bug_02_out_of_range_query_ids_are_a_422`, E2E `[API-02]` |
| BUG-03 | Low | `GET /api/allocations?week_start=9999-12-31` returned 500 | Dates were unbounded; adding a week to the year 9999 overflows Python's date range | Shared type `SafeDate`: only 2020-01-01 to 2100-12-31, otherwise **422 "Dates must be between 2020 and 2100."** (also on `/api/forecasts?week_start=`) | `test_bug_03_*`, E2E `[API-03]` |
| BUG-04 | Medium | Dashboard: From/To dates in year 9999 returned 500 and the page showed an error | Same unbounded dates in `GET /api/dashboard/metrics` | `SafeDate` on `start` and `end` (**422**); the Dashboard also checks the dates before sending anything and shows "Dates must be between 2020 and 2100." inline, and the date pickers are limited to that range | `test_bug_04_*`, E2E `[API-04]`, `[DASH-08]` |
| BUG-05 | Low | `GET/POST /api/dashboard/summaries/0000-01...` returned 500 | The month pattern accepted year 0000, which is not a valid date | Shared type `Month` (2020-01 to 2100-12): **422 "The month must be between 2020-01 and 2100-12"** on all three summary routes | `test_bug_05_*`, E2E `[API-05]` |
| BUG-06 | Medium | A NUL (or any control) character in a shortage note, allocation edit note, summary text, login email or password returned 500, including on the logged-out login route | Postgres text and JSONB cannot store NUL and nothing checked text before it reached the database | Shared text types: `LineText` (no control characters at all) for names, units, emails, passwords and donor names; `BlockText` (new lines and tabs allowed) for notes and summaries: **422 "Text can't contain control characters."** Text the model writes (extracted items, donor, notes, raw JSONB output, summary drafts, allocation reasons) is cleaned or rejected too: this was a second, hidden route to the same 500, found while writing the regression test. The forms check the same rules inline | `test_bug_06_*`, `test_text_the_model_wrote_is_cleaned_of_control_characters`, `test_validated_types.py`, E2E `[API-06]` |
| BUG-07 | Medium | Donations filter links (32 px) and Review/View links (20 px) under 1024 px wide | They were styled links, outside the global rule that sizes buttons | Filter links, row links and the new paging links are at least 44 px tall below 1024 px | E2E `[SHELL-09]` (all pages, 375 and 768 px) |
| BUG-08 | Low | A missing record inside the app shell answered HTTP 200 | `(app)/loading.tsx` put a loading boundary above every page, so the response had already started (status 200) when `notFound()` ran | Loading screens now sit beside the list pages (route groups `(list)`), so the detail page has no boundary above it and `notFound()` gives a real **404** with the not-found page | E2E `[SHELL-13]`, `[SHELL-10]`, `[SHELL-11]` |
| BUG-09 | Medium | The donation list showed only the newest 100 of 3,626 donations | The API default `limit=100`, no paging and no total | `GET /api/donations?limit&offset` with an `X-Total-Count` header; the page shows 50 per page, "Showing 1–50 of 3,626", Previous and Next, and copes with odd `?page=` values | `test_bug_09_*` (3), E2E `[DON-09]`, `[DON-10]`, `[DON-11]` |
| BUG-10 | High | Whole app while the database is down (found by hand: `docker compose stop`) | Database driver errors were not handled, so they fell through to the generic 500; the envelope had no request id; the server-side session check threw a generic error, which showed as a crash on reload | Global handlers: a database that cannot be reached is **503 `service_unavailable`** (with `Retry-After`), a value the database refuses is 422, anything else is a 500 envelope; **every error carries a `request_id`** (also the `X-Request-ID` header, and the log keeps the full detail). `/api/health` answers 503 with `details: {"database": "down"}`. Server pages that cannot reach the API go to `/unavailable` ("temporarily unavailable" with Try again, which returns to the page); an outage is never treated as a logout. Buttons show the same message | `test_error_handling.py` (10), E2E `[OUT-01]`, `[OUT-02]`, `[OUT-03]` |

## Found while fixing

- **Try again did not retry.** On a page whose server data failed, the error screen's Try again only redrew
  the page (Next.js `reset()`), so it stayed broken after the database came back. It now refreshes the data too.
  Found by E2E `[SHELL-12]`.
- **`/admin/*` was missing from the login redirect list**, so a logged-out visitor to the dashboard got a
  flash of the loading screen before the redirect. Now covered, and the same step passes the page address to
  the unavailable screen.

## Not bugs, but worth knowing

- Accessibility findings are separate: [a11y-report.md](a11y-report.md). They are not fixed in this stage.
- Dates and numbers that look odd but are accepted on purpose: decimal quantities such as 2.5 cases, and a
  decimal allocation amount such as 12.345 lb (rounded to hundredths by the server). Expiry dates are limited
  to 2020 to 2100 like every other date.
- `make test` and `make e2e` share the test database and must run one after the other.


## Bugs found in Stages 12 and 13

Same severity scale as above, plus the **axe impact** in brackets for the four automated accessibility findings.
Security findings that are missing protections (no token revocation, no CSRF check, no security headers, no rate limits and so
on) have their own IDs, **SEC-01 to SEC-23**, and are listed with severity and status in
[`docs/security/audit.md`](../security/audit.md); they are not repeated here. The numbering continues from BUG-10 across both tables.

### (a) Defects in committed code

| ID | Severity | Where | How found | Root cause | Fix | Regression tests |
| --- | --- | --- | --- | --- | --- | --- |
| BUG-11 | Medium | Application log, any database error | Stage 12: a log-hygiene test written during the security audit forced a database error and read the log | A failed statement's error text includes the offending row values (for example the email in "Key (email)=(...)"), and the engine passed them on | `hide_parameters=True` on the engine, and a log formatter that removes the database's DETAIL, CONTEXT and HINT lines | `test_a_database_error_does_not_put_the_values_in_the_log`, `test_the_engine_hides_parameters` |
| BUG-12 | Low | `backend/scripts/seed.py` | Stage 12: bandit rule B608 flagged it | Table names were put into SQL with f-strings (from a fixed list, not user input, but the pattern is the one injection uses) | One `quote()` helper that quotes every identifier | `test_the_seed_script_quotes_every_table_name_it_puts_in_sql`, `make security` |
| BUG-13 | High (only when stock is short) | Allocation optimizer | Stage 13: measuring the share of forecast demand met by group, including a half-stock stress test | Every pound toward a pantry's forecast earned the same reward, so the small per-mile penalty was the only tie-breaker and scarce stock filled the nearest pantries completely first. With half the stock the farthest third of pantries received 1.4% of their forecast (59 points below average) and one county was 25 points below | Tiered coverage: the forecast is split into ten slices, each worth 0.02 less per pound than the one before and always more than the biggest distance difference, so scarce stock is shared by share of demand | `test_scarce_stock_is_spread_by_share_of_demand_not_filled_nearest_first`, `test_distance_never_outweighs_unmet_demand_however_large_the_penalty`, `make fairness` |
| BUG-14 | High (axe: critical) | Donation review, items grid | Stage 10 axe scan (`aria-required-children`), fixed in Stage 13 | The grid's rows were `role="row"` containers whose children had no cell roles, and its header row was hidden from screen readers | Column headers and `role="cell"` on every cell; a row label on each field ("Item (row 2)") | `A11Y-04`, `A11Y-28`, `A11Y-13` |
| BUG-15 | Medium (axe: serious) | Impact dashboard, headline figures | Stage 10 axe scan (`definition-list`) | The explanatory note sat in a paragraph between the term and the value inside a definition list | Note moved inside the value | `A11Y-07`, `A11Y-14` |
| BUG-16 | Low (axe: minor) | Donations list table | Stage 10 axe scan (`empty-table-header`) | The last column header was empty | Screen-reader-only text "Open", header scopes, caption | `A11Y-03`, `A11Y-28` |
| BUG-17 | Low (axe: minor) | Forecasts accuracy table | Stage 10 axe scan (`empty-table-header`) | The first column header was empty | Screen-reader-only text "Measured on", header scopes, caption | `A11Y-05`, `A11Y-28` |

### (b) Defects caught before commit (in work in progress, never shipped)

| ID | Severity if shipped | Where | How found | Root cause | Fix | Regression tests |
| --- | --- | --- | --- | --- | --- | --- |
| BUG-18 | Medium | Streaming request-size limit (Stage 13a) | The new test for a chunked body returned 400, not 413 | FastAPI turns any exception raised while it reads the body into its own 400, so a limit that raised never reached the client | The middleware sends the 413 itself, ends the read and drops what the application sends afterwards | `test_a_chunked_json_body_over_the_limit_is_refused_without_a_content_length`, `test_a_request_that_lies_about_a_small_length_is_stopped_when_it_exceeds_the_limit` |
| BUG-19 | Medium | Raw-output retention (Stage 13a) | The new check constraint rejected the clearing statement | Assigning `None` to a JSONB column through SQLAlchemy stores the JSON value `null`, not SQL `NULL` | The service writes SQL `NULL` explicitly | `test_output_reviewed_more_than_90_days_ago_is_cleared`, `test_the_database_refuses_a_cleared_marker_on_a_donation_that_still_has_output` |
| BUG-20 | Medium | Modal dialog (Stage 13b) | Keyboard test `A11Y-27`: re-opening a dialog straight after Escape did nothing | The browser delivers a dialog's `close` event as a later task, after the next key press and click. The parent still thought the dialog was open, and the late event then closed the newly opened one | The dialog handles Escape itself and updates its parent at once, and ignores a late `close` event if it has been re-opened | `A11Y-27` (three tests) |
| BUG-21 | Low | Donations list at 768 px (Stage 13b) | Existing test `DON-07` (no sideways scrolling) failed by 1 px | A screen-reader-only header cell is absolutely positioned, and in the last column it sat at the right edge and widened the page | The cell is made a positioning context | `DON-07`, `A11Y-32` |
| BUG-22 | Medium (axe: serious) | Scrollable tables (Stage 13b) | Axe gate (`scrollable-region-focusable`) on the table view | A scrollable region had no way to be reached or scrolled with the keyboard | Table regions are focusable and named | `A11Y-14`, `A11Y-28` |
| BUG-23 | Low | Skip link (Stage 13b) | Existing test `SHELL-09` (controls at least 44 px tall) counted it | The hidden skip link is 1 px tall, and was only a normal size by accident when shown | Shown at 44 px minimum; the test ignores the visually hidden form | `SHELL-09`, `A11Y-20` |

### Found while building, in the tests and harness (not product defects)

These cost time and are recorded so they are not repeated; none reached a user.
- Playwright run by hand without `.env` loaded has empty demo passwords, so every login test fails (`make e2e` exports them).
- WebKit's default is that Tab visits form fields only; links and buttons need Option+Tab, so keyboard tests use Alt+Tab there.
- `Control+A` is not select-all on macOS (`ControlOrMeta+A`); a script-injected `<script>` through `page.evaluate` runs even under a strict policy, so the CSP test adds unnonced markup to the real response instead.
- `ruff format` silently turned some scripted edits into no-ops; each replacement was checked.
- A 55-minute E2E run (53 failures with 60-second timeouts) after the new markup changed what earlier tests counted: the items grid now has a header row, `getByLabel("To")` matched a chart, and the skip link was measured as a control.
