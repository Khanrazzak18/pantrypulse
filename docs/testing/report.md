# PantryPulse testing report

What was tested, how, what broke, what was done about it, and what the numbers are at the end of
assignment 5.4 (Stages 10 to 14). The baseline, "before 5.4", is the Stage 9 commit (`f2f4909`): 527 test
functions, 840 test cases, no end-to-end tests, no checklist, no accessibility scan, no fuzz test, no
security tests.

Related documents: [feature checklist](checklist.md) (every feature, button and error state, with its test),
[bug log](bugs.md) (details), [accessibility scan](a11y-report.md), [security audit](../security/audit.md),
[security checklist](../security/checklist.md), [accessibility](../accessibility.md),
[responsible AI](../responsible-ai.md), [fairness](../eval/fairness.md).

## 1. Testing approach

Eight layers, from the cheapest and fastest to the most realistic. Tests are written before the code they
check, seen failing, then made to pass; a stage is not done until `make test` passes.

| Layer | What it does | Where and how to run | What it guards |
| --- | --- | --- | --- |
| **Manual pass** | A walkthrough of every feature as each role in a real browser against the real app, real database and real Bedrock, with the browser console and the API log checked | Stage 9 and Stage 14 walkthroughs, written up in the [dev log](../dev-log.md); BUG-10 (database down) was found this way | Things automation cannot judge: how it reads, flicker, a crash after `docker compose stop` |
| **pytest** | Unit and API tests against a separate test database and a scripted fake AI (a guard fails any test that tries to create an AWS client) | `backend/tests`, `make test` | Constraints and migrations, auth and lockout, intake, forecasting and its leakage checks, the optimizer and its fairness, allocation workflow, error envelopes, validation, security controls, report generation |
| **Playwright end-to-end** | Drives the real pages signed in as each role against its own API (port 8101) on the test database with a mock AI, in **4 browser projects**: Chromium at 375, 768 and 1280 px and WebKit at 1280 px | `frontend/e2e`, `make e2e` | Every row of the checklist, page by page: forms, errors, dialogs, outages, responsive layout, 44 px tap targets, redirects, security headers and CSP in a real browser |
| **Fuzz test** | Sends hostile ids, dates, numbers, long text, control characters, SQL and HTML to every API route as a logged-out caller, a pantry manager and an admin, plus hostile upload names and contents; fails on any HTTP 500, any change to rows, or a slow response | `backend/tests/test_api_fuzz.py` | The whole class of "odd input crashes the server" (BUG-01 to BUG-06) and injection |
| **Role-by-route test** | Reads the API's own route list; every route must have an entry in an access table, and each role is tried against each route (401 logged out, 403 wrong role, a manager only reaches their own pantry) | `backend/tests/test_authorization_matrix.py`, `make security` | A new route nobody remembered to protect |
| **Axe scans** | axe-core on 23 pages and page states (errors showing, dialogs open, table views open) for every role at four widths; **any WCAG 2.0/2.1 A or AA violation fails the run** | `frontend/e2e/a11y.spec.ts`, `make e2e` | Accessibility regressions (target: zero violations) |
| **Keyboard-only journeys** | Four journeys with no mouse (the test fails on any pointer event): sign in; upload, review and confirm a donation; approve and edit a shipment; send a shortage report at 375 px; plus dialog open and close | `frontend/e2e/a11y-features.spec.ts` | What axe cannot see: where focus goes, what is announced, dialogs, text alternatives to charts |
| **Live prompt-injection check** | Three hostile manifests (override and delete, fake items and a confirm flag, exfiltrate the prompt) sent through the real intake path to the **real model** | `backend/eval/injection_check.py`, result in [injection-check.md](../security/injection-check.md) | A model hijacked by a manifest cannot change other records or bypass review |

Also run, as part of the same discipline: **`make security`** (secret scan over the whole git history and
working tree, bandit, pip-audit, an npm audit gate, and the security tests), **`make eval`** (intake accuracy
against 50 golden manifests, calls Bedrock), **`make backtest`** (forecast error, rolling origin over 12 weeks),
**`make simulate`** (12-week allocation replay) and **`make fairness`** (share of demand met by group).

How the end-to-end layer is kept honest: every Playwright test cites a checklist row by ID in its title, a pytest
test fails if one cites a row that does not exist, and the checklist is regenerated from the last run by every
`make e2e`. The mock AI and the reset route live only in `backend/scripts/e2e_server.py`; a test proves the
normal app cannot load them.

## 2. Results

### 2.1 Counts

<!-- GENERATED:counts -->
_Generated 2026-10-11 22:04 by `make e2e` from the last run._

| Measure | Count |
| --- | --- |
| pytest test functions | 724 |
| pytest test cases (parametrized tests run once per parameter) | 1176 |
| End-to-end test runs (all projects) | 1100 |
| of which passed / failed / skipped by design | 1045 / 0 / 55 |
| Checklist items | 229 |
| of which automated | 229 (6 pytest only, 105 end-to-end only, 118 both) |
| Accessibility scans (axe) | 108 |

| Browser project | Passed | Failed | Skipped by design |
| --- | --- | --- | --- |
| chromium-1280 | 271 | 0 | 4 |
| chromium-375 | 260 | 0 | 15 |
| chromium-768 | 258 | 0 | 17 |
| webkit-1280 | 256 | 0 | 19 |
<!-- /GENERATED:counts -->

Before 5.4 (Stage 9, `f2f4909`): 527 pytest functions, 840 cases; 0 end-to-end runs; 0 checklist items; 0 axe scans.

### 2.2 Final verification run

<!-- FINAL-RUN -->
Run on 2026-10-11, from a clean start (the database volume deleted), exactly as the README describes.

| Step | Result |
| --- | --- |
| `docker compose down -v`, `make db`, `make migrate` | fresh Postgres 16; all 9 migrations applied |
| `make seed`, `make backtest` | 3 years of synthetic data; backtest WAPE 10.7% (LightGBM) against 14.5% (last year's value); P10 to P90 coverage 77.2% |
| `make test` | **1,176 passed** (88 s); ruff, frontend lint, typecheck and production build pass |
| `make e2e` | **1,045 passed, 0 failed, 55 skipped by design** (27.5 min, 4 browser projects); 229 of 229 checklist items automated and passing; **108 axe scans, 0 violations, 0 advisory** |
| `make security` | gitleaks: no leaks in the git history or the working tree; bandit: no issues; pip-audit: no known vulnerabilities; npm gate: no high or critical advisory (1 accepted, dev only); **189 security tests passed** |

**Manual walkthrough on port 3001** (real database, real Bedrock, built-in browser; the five files in `~/Desktop/pp-test` were uploaded
with a real browser because the pane has no file picker):

| Role | What was done | Result |
| --- | --- | --- |
| Logged out | `/admin/dashboard` redirects to sign-in with `next`; empty form; wrong password | Inline messages; one generic "Incorrect email or password."; `next` honoured after sign-in |
| Admin | Dashboard (KPI cards, five charts with summaries, table view, date preset), AI summary draft and approval, weekly refresh | All worked; refresh 12.8 s, 708 proposed shipments; the approved summary locked |
| Coordinator | Pantries (85); upload of all five test files; review, edit and confirm a donation; reject through the dialog (Escape, then confirm); forecast run (3.8 s, 680 forecasts) and chart table view; allocations: approve, edit (invalid then valid amount), reject, approve all 703 | `empty.pdf`, `virus.exe`, `big.pdf` refused with readable messages; `good-email.eml` read in 6.0 s (6 items, 1 field unsure), `photo.png` in 7.7 s (5 items, 4 unsure); every action announced; coordinator sent away from the dashboard |
| Pantry manager (375 px) | Deliveries; shortage report (empty submit, then a valid one); staff pages and dashboard | Validation, then "Thank you. Your dairy report is saved…"; redirected to `/pantry` from both staff pages |
| Everyone | 404 page; database stopped mid-session | Readable not-found page; API 503 envelope and an "unavailable" page, and **Try again** recovered with the session intact |

Browser console and API log for the whole session: **no application errors, no tracebacks**. The only console errors were two deliberate probes
(the wrong-password 401 and a missing page's 404); the API log held one warning (that wrong password) and its 4xx responses were 14
signed-out session checks and that one login.

Nothing was broken by the walkthrough, so no fix was needed. Observations, not changed: the sample manifest's expiry date (10 Oct) was
already past on the app's clock, so confirming it was correctly refused until the date was corrected; the pantry portal shows far-future
"use by" dates without a year; Next.js's development badge overlaps the footer text in development mode only.
<!-- /FINAL-RUN -->

### 2.3 Checklist summary by role

Status of each checklist row: **passing** means every automated test for it passed in the last run (a row
counts under each role it names).

<!-- GENERATED:by-role -->
| Role | Items | Passing | Failing | Known bug | Not run |
| --- | --- | --- | --- | --- | --- |
| Admin | 41 | 41 | 0 | 0 | 0 |
| All | 36 | 36 | 0 | 0 | 0 |
| All staff | 2 | 2 | 0 | 0 | 0 |
| Coordinator | 108 | 108 | 0 | 0 | 0 |
| Logged out | 24 | 24 | 0 | 0 | 0 |
| Manager | 19 | 19 | 0 | 0 | 0 |
| Pantry manager | 2 | 2 | 0 | 0 | 0 |
| **Total** | **232** | **232** | **0** | **0** | **0** |
<!-- /GENERATED:by-role -->

### 2.4 Checklist summary by page

<!-- GENERATED:by-page -->
| Page | Items | Passing | Failing | Known bug | Not run |
| --- | --- | --- | --- | --- | --- |
| / | 1 | 1 | 0 | 0 | 0 |
| /admin/* | 1 | 1 | 0 | 0 | 0 |
| /admin/dashboard | 30 | 30 | 0 | 0 | 0 |
| /api | 5 | 5 | 0 | 0 | 0 |
| /api/* | 1 | 1 | 0 | 0 | 0 |
| /api/* filters | 1 | 1 | 0 | 0 | 0 |
| /api/admin | 1 | 1 | 0 | 0 | 0 |
| /api/allocations | 2 | 2 | 0 | 0 | 0 |
| /api/dashboard/metrics | 1 | 1 | 0 | 0 | 0 |
| /api/dashboard/summaries | 1 | 1 | 0 | 0 | 0 |
| /api/dashboard/summaries/{month} | 1 | 1 | 0 | 0 | 0 |
| /api/donations/{id}, /api/pantries/{id}, /api/allocations/{id}/approve | 1 | 1 | 0 | 0 | 0 |
| /api/forecasts/series | 1 | 1 | 0 | 0 | 0 |
| /api/health | 1 | 1 | 0 | 0 | 0 |
| /api/pantry | 1 | 1 | 0 | 0 | 0 |
| /coordinator | 6 | 6 | 0 | 0 | 0 |
| /coordinator, /coordinator/donations, /coordinator/forecasts, /coordinator/allocations | 2 | 2 | 0 | 0 | 0 |
| /coordinator/allocations | 25 | 25 | 0 | 0 | 0 |
| /coordinator/allocations, /coordinator/donations/[id] | 1 | 1 | 0 | 0 | 0 |
| /coordinator/donations | 26 | 26 | 0 | 0 | 0 |
| /coordinator/donations, /coordinator/allocations, /pantry, /admin/dashboard | 1 | 1 | 0 | 0 | 0 |
| /coordinator/donations/99999999 | 2 | 2 | 0 | 0 | 0 |
| /coordinator/donations/[id] | 23 | 23 | 0 | 0 | 0 |
| /coordinator/donations?added= | 1 | 1 | 0 | 0 | 0 |
| /coordinator/donations?page= | 1 | 1 | 0 | 0 | 0 |
| /coordinator/donations?status= | 1 | 1 | 0 | 0 | 0 |
| /coordinator/forecasts | 13 | 13 | 0 | 0 | 0 |
| /coordinator/forecasts, /admin/dashboard | 2 | 2 | 0 | 0 | 0 |
| /login | 18 | 18 | 0 | 0 | 0 |
| /login, /coordinator/allocations, /pantry, /coordinator/forecasts | 1 | 1 | 0 | 0 | 0 |
| /login, /coordinator/donations, /coordinator/allocations, /pantry | 1 | 1 | 0 | 0 | 0 |
| /login, /coordinator/donations/[id], /pantry, /coordinator/allocations, /admin/dashboard | 1 | 1 | 0 | 0 | 0 |
| /login?next= | 2 | 2 | 0 | 0 | 0 |
| /nope | 1 | 1 | 0 | 0 | 0 |
| /pantry | 18 | 18 | 0 | 0 | 0 |
| /unavailable | 1 | 1 | 0 | 0 | 0 |
| /unavailable, not-found, /coordinator/donations (AI down) | 1 | 1 | 0 | 0 | 0 |
| URLs of another role | 1 | 1 | 0 | 0 | 0 |
| every API route | 1 | 1 | 0 | 0 | 0 |
| every page | 23 | 23 | 0 | 0 | 0 |
| every page (under 1024 px) | 1 | 1 | 0 | 0 | 0 |
| every page (under 768 px) | 1 | 1 | 0 | 0 | 0 |
| every page with a table | 1 | 1 | 0 | 0 | 0 |
| every route | 1 | 1 | 0 | 0 | 0 |
| every signed-in page | 1 | 1 | 0 | 0 | 0 |
| not found page | 1 | 1 | 0 | 0 | 0 |
| note, summary and email fields | 1 | 1 | 0 | 0 | 0 |
| **Total** | **229** | **229** | **0** | **0** | **0** |
<!-- /GENERATED:by-page -->

The full table (steps, inputs, expected result and the tests for each row) is [checklist.md](checklist.md).

## 3. Bugs

Twenty-three bugs were found and fixed in 5.4. Each has a regression test that was written first and seen
failing. Severity: **High** loses data, leaks data or blocks a main job; **Medium** shows a wrong or broken
result for input a real user can type; **Low** needs an unusual request or is cosmetic. Details, in full, are in
[bugs.md](bugs.md). Missing protections found by the security audit have their own IDs (SEC-01 to SEC-23, PROC-01, PROC-02) and
are in section 4.

| ID | Sev. | Stage found | How found | Root cause | Fix | Regression test |
| --- | --- | --- | --- | --- | --- | --- |
| BUG-01 | Medium | 10 | End-to-end edge-case tests sending ids above 2,147,483,647 | Path ids were plain integers; a 20-digit id reached a 32-bit database column | Shared `PathId` type; out-of-range path id is a 404 | `test_bug_01_*`, `API-01` |
| BUG-02 | Low | 10 | Same probing, query ids | Query ids were unbounded integers | Shared `PositiveId` type, 422 | `test_bug_02_*`, `API-02` |
| BUG-03 | Low | 10 | Probing with `week_start=9999-12-31` | Dates unbounded; adding a week to year 9999 overflows | Shared `SafeDate` (2020 to 2100), 422 | `test_bug_03_*`, `API-03` |
| BUG-04 | Medium | 10 | Probing the dashboard with year 9999 | Same unbounded dates | `SafeDate`, and the page checks inline | `test_bug_04_*`, `API-04`, `DASH-08` |
| BUG-05 | Low | 10 | Probing the summary routes with month `0000-01` | Month pattern accepted year 0000 | Shared `Month` type, 422 | `test_bug_05_*`, `API-05` |
| BUG-06 | Medium | 10 | Probing text fields with a NUL character | Postgres cannot store NUL and nothing checked text first (also reachable through text the model wrote) | Shared `LineText` and `BlockText` types; model text cleaned or rejected | `test_bug_06_*`, `API-06` |
| BUG-07 | Medium | 10 | End-to-end tap-target test | Donation links were outside the 44 px rule for buttons | Links sized at least 44 px below 1024 px | `SHELL-09` |
| BUG-08 | Low | 10 | End-to-end status-code test | A loading boundary above every page started the response (status 200) before `notFound()` | Loading screens moved beside the list pages; real 404 | `SHELL-13`, `SHELL-10` |
| BUG-09 | Medium | 10 | End-to-end test noticing 100 of 3,626 donations | API default limit 100, no paging, no total | `limit`/`offset` and `X-Total-Count`; paged page | `test_bug_09_*`, `DON-09`, `DON-10` |
| BUG-10 | High | 10 | By hand: `docker compose stop` while using the app | Database driver errors fell through to a generic 500, no request id, session check crashed | Global handlers: 503 `service_unavailable`, request ids, `/unavailable` page, health 503 | `test_error_handling.py`, `OUT-01` to `OUT-03` |
| BUG-11 | Medium | 12 | Log-hygiene test written during the security audit | Database error text includes the row values | `hide_parameters=True` and a log formatter | `test_a_database_error_does_not_put_the_values_in_the_log` |
| BUG-12 | Low | 12 | bandit B608 | Table names built with f-strings in `seed.py` | One `quote()` helper | `test_the_seed_script_quotes_every_table_name_it_puts_in_sql` |
| BUG-13 | High (when stock is short) | 13 | Fairness measurement and half-stock stress test | Equal reward per pound left distance as the only tie-breaker, so scarce stock filled near pantries first (far band 1.4% of forecast) | Tiered coverage in the optimizer | `test_scarce_stock_is_spread_by_share_of_demand_not_filled_nearest_first` |
| BUG-14 | High (axe critical) | 10 (fixed 13) | Axe scan, `aria-required-children` | Items grid rows without cell roles, header hidden from screen readers | Column headers, cell roles, row labels | `A11Y-04`, `A11Y-28` |
| BUG-15 | Medium (axe serious) | 10 (fixed 13) | Axe scan, `definition-list` | A paragraph inside a definition list | Note moved inside the value | `A11Y-07` |
| BUG-16 | Low (axe minor) | 10 (fixed 13) | Axe scan, `empty-table-header` | Empty last header on the donations table | Hidden text, scopes, caption | `A11Y-03` |
| BUG-17 | Low (axe minor) | 10 (fixed 13) | Axe scan, `empty-table-header` | Empty first header on the accuracy table | Hidden text, scopes, caption | `A11Y-05` |
| BUG-18 | Medium (not shipped) | 13a | New streaming-limit test returned 400 | FastAPI turns an exception raised while reading the body into a 400 | The middleware sends the 413 itself | `test_a_chunked_json_body_over_the_limit_is_refused_without_a_content_length` |
| BUG-19 | Medium (not shipped) | 13a | New check constraint rejected the clearing statement | `None` in a JSONB column is stored as JSON `null`, not SQL `NULL` | Write SQL `NULL` explicitly | `test_output_reviewed_more_than_90_days_ago_is_cleared` |
| BUG-20 | Medium (not shipped) | 13b | Keyboard test: dialog would not re-open after Escape | The browser delivers `close` as a later task; a stale event closed the new dialog | Handle Escape directly; ignore a stale `close` | `A11Y-27` |
| BUG-21 | Low (not shipped) | 13b | Existing `DON-07` failed by 1 px at 768 px | A hidden header cell widened the page | Make the cell a positioning context | `DON-07` |
| BUG-22 | Medium (not shipped) | 13b | Axe, `scrollable-region-focusable` | Scrollable table region not reachable by keyboard | Focusable, named region | `A11Y-14` |
| BUG-23 | Low (not shipped) | 13b | Existing `SHELL-09` counted it as a 1 px control | Hidden skip link's size | 44 px when shown | `SHELL-09`, `A11Y-20` |

By severity: High 3 (BUG-10, BUG-13, BUG-14), Medium 11, Low 9. "Not shipped" means the defect was caught in work
in progress, before the commit that would have released it. Time lost to mistakes in the tests and harness
(WebKit's Tab key, `Control+A` on macOS, running Playwright without `.env`) is listed in bugs.md so it is not repeated.

## 4. Security measures

The audit is [audit.md](../security/audit.md): 25 items (SEC-01 to SEC-23 plus two process findings) with OWASP Top 10 and OWASP LLM Top 10 category, severity,
evidence, fix, test and status. The in-place measures, each with the test that proves it, are in
[the security checklist](../security/checklist.md) (14 areas).

| Severity | Found | Fixed or verified | Accepted | Open |
| --- | --- | --- | --- | --- |
| High | 4 | 4 | 0 | 0 |
| Medium | 10 | 8 | 2 | 0 |
| Low | 8 | 8 | 0 | 0 |
| Process | 3 | 3 | 0 | 0 |

- **Secrets:** secret scan over the full history and tree (nothing found; `.env` never committed), a pre-commit hook, a rotated
  AWS key. **IAM:** `bedrock:InvokeModel` only, on one model; verified live that listing is denied.
- **Sessions and access:** sessions revoked on logout and on a role, pantry, password or active-flag change; per-email and per-address
  login lockout in the database; every route in an access table checked for every role.
- **Web:** nonce-based CSP with no inline scripts, frame blocking, nosniff, Referrer-Policy, Permissions-Policy, HSTS over https;
  an Origin and fetch-metadata check against CSRF; `X-Forwarded-For` trusted only from listed proxies; request size counted as it streams in.
- **Cost and abuse:** per-user hourly limits on uploads, each AI endpoint and the weekly refresh; a token cap and time limit inside every model call.
- **LLM:** untrusted manifest text in the user turn, one forced data-return tool, validated output, number checks, a person approves everything;
  live injection check against the real model: 3 of 3 manifests produced only their legitimate item.
- **Privacy:** no credentials, manifests or database values in logs; raw model output cleared 90 days after review.
- **Accepted on purpose:** CSP `style-src 'unsafe-inline'` (Next.js and Recharts write inline styles) and one dev-only npm advisory with no patch;
  rationale and revisit conditions in the checklist.
- **Tools run by `make security`:** gitleaks (history and tree), bandit (no issues), pip-audit (no known vulnerabilities), the npm gate.

## 5. Accessibility

Target WCAG 2.1 AA; built and tested features are in [accessibility.md](../accessibility.md). Summary: a skip link, landmarks and one `h1`,
a title per route, a 3 px visible focus outline, form errors linked with `aria-describedby` and focus moved to the first error, status and alert
announcements, modal dialogs that trap focus and return it, table captions and header scopes, a text summary and a "View as table" for all six
charts, meaning never carried by colour alone, reduced-motion support, 200% and 400% zoom, and four keyboard-only journeys. The axe gate has
**zero** violations (and zero advisory findings) across the scanned pages and states. Not done: a manual screen-reader pass.

## 6. Fairness

Share of P50 demand met, by county, distance band and pantry size; rule: no group more than 10 percentage points below the average.
Method and tables: [fairness.md](../eval/fairness.md); reproduce with `make fairness`.

| Case | Before | After |
| --- | --- | --- |
| Normal stock, worst group | -0.6 pp (size: small) | -0.4 pp (county: Ashford) |
| Half stock, farthest third of pantries | 1.4% met (-59.4 pp) | 56.9% met (-3.9 pp) |
| Half stock, worst county | Elmhurst -25.3 pp | -1.5 pp |
| Half stock, worst single pantry | 0.0% | 54.5% |
| Half stock, overall demand met | 60.8% | 60.8% |

Trade-offs: with half stock, pound-miles rise from 53.1M to 63.6M (+20%) and trip miles from 26,301 to 47,839 (+82%); with normal stock short
pantry-weeks rise from 33.2% to 34.8% (manual rule: 31.3%) because a shortage is spread over more pantries; spoilage is the same or lower.
Fairness was only visible under scarcity: with normal stock every group is within one point of the average whatever the objective.

## 7. Known limits of this testing

- The data is synthetic; accuracy, spoilage and fairness figures show the method works, not what the food bank will see.
- The end-to-end layer uses a scripted mock AI. Real model behaviour is covered by the intake eval (`make eval`), the live injection check
  and the manual walkthrough, not by every test.
- No manual screen-reader test and no third-party penetration test have been done.
- The tests ran on one machine against local Postgres; deployment (App Runner, RDS, Cognito, S3) was never built, so none of it is tested.
