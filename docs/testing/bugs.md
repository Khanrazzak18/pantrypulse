# Bugs found in Stage 10 (testing)

Found by the end-to-end tests (`make e2e`) and by probing the API with out-of-range and odd input.
**None are fixed yet**: that is a later stage. Each has a Playwright test marked `test.fail()` with
its ID in the title, so `make e2e` stays green today and the test turns red the moment the bug is
fixed (remove the `test.fail` line then). Accessibility findings are separate:
[a11y-report.md](a11y-report.md).

Severity: **High** loses data, leaks data or blocks a main job; **Medium** shows a wrong or broken
result for input a real user can type; **Low** needs an unusual request or is cosmetic.

| ID | Where | Steps to reproduce | Expected | Actual | Severity |
| --- | --- | --- | --- | --- | --- |
| BUG-01 | `GET /api/donations/{id}`, `GET /api/pantries/{id}`, `POST /api/allocations/{id}/approve`, `/reject`, `/edit`, `POST /api/allocations/runs/{id}/reasons`; page `/coordinator/donations/{id}` | Sign in as admin. Request `/api/donations/9999999999` (or any id above 2,147,483,647). In the browser open `/coordinator/donations/9999999999`. Test: `[API-01][BUG-01]`, `[SHELL-10][BUG-01]` | 404 (or 422) in the error envelope; the page shows "We couldn't find that" | HTTP 500 `internal_error`; the page shows "Something went wrong". The id is passed to Postgres as a 32-bit integer and the database error is not handled | Medium |
| BUG-02 | `GET /api/forecasts/series?pantry_id=` | `GET /api/forecasts/series?pantry_id=99999999999&category=produce`. Test: `[API-02][BUG-02]` | 404 or 422 | HTTP 500. Same cause as BUG-01 (`GET /api/forecasts?pantry_id=` with the same value returns 200 with an empty list, so the routes disagree) | Low |
| BUG-03 | `GET /api/allocations?week_start=` | `GET /api/allocations?week_start=9999-12-31`. Test: `[API-03][BUG-03]` | 200 with an empty list, or 422 | HTTP 500: the delivery-date arithmetic runs past the last date Python can represent | Low |
| BUG-04 | `GET /api/dashboard/metrics`; Dashboard page From and To date fields | On the Dashboard type From 9999-12-01 and To 9999-12-31 (the browser date picker allows it), or call `?start=9999-01-01&end=9999-12-31`. Test: `[API-04][BUG-04]`, `[DASH-08][BUG-04]` | The "no data in this range" message, or a message that the date is out of range | HTTP 500, shown as "Something went wrong" (the date range check allows any span under 260 weeks, so year 9999 reaches the date arithmetic that overflows) | Medium |
| BUG-05 | `GET /api/dashboard/summaries/{month}` and `POST .../draft` | `GET /api/dashboard/summaries/0000-01` (the pattern accepts `0000`). Test: `[API-05][BUG-05]` | 404 or 422 | HTTP 500: year 0 is not a valid Python date | Low |
| BUG-06 | Text fields that reach the database: shortage report note, allocation edit note, monthly summary text, login email | Send a NUL character (`\u0000`) in the field, for example `POST /api/pantry/shortage-reports` with `{"category":"dairy","severity":1,"note":"a\u0000b"}`, or `POST /api/auth/login` with `"email":"a\u0000b@c.de"`. Test: `[API-06][BUG-06]` | 422 in the error envelope | HTTP 500 `internal_error` (Postgres text cannot hold NUL). The login route is open to anyone logged out, so anyone can trigger a server error log entry. The donation item name is already refused with 422, so the checks are inconsistent | Medium |
| BUG-07 | Donations page, under 1024 px wide: filter links (All, Needs review, Confirmed, Rejected) and the Review/View link in each row | Open `/coordinator/donations` at 375 or 768 px and measure the controls. Test: `[SHELL-09][BUG-07]` | Every tap target at least 44 px tall (the project rule, and the global rule applied to buttons) | Filter links are 32 px tall and the row links 20 px, because they are links styled with padding rather than the buttons the global rule covers | Medium |
| BUG-08 | Any page inside the app shell for a record that does not exist, for example `/coordinator/donations/99999999` | Open it and read the HTTP status. Test: `[SHELL-13][BUG-08]` | HTTP 404 with the not-found page | HTTP 200 with the not-found content (the loading screen has already started streaming), so monitors and crawlers see a normal page | Low |
| BUG-09 | `/coordinator/donations` | Open the list on the seeded data (3,626 imported donations; any database with more than 100 donations shows it). Test: `[DON-09][BUG-09]` | Every donation reachable: paging, search, or a "showing 100 of N" note | The list shows only the newest 100 rows (API default `limit=100`), so on the seeded data 3,526 donations cannot be reached from the page and nothing says so | Medium |

## Not bugs, but worth knowing

- A scan with axe-core found 4 unique accessibility violations (1 critical, 1 serious, 2 minor); see
  [a11y-report.md](a11y-report.md). Automated scans find only part of the real problems.
- Dates and numbers that look odd but are accepted on purpose: an expiry date in the year 9999 on the
  review page (saved as entered), decimal quantities such as 2.5 cases, and a decimal allocation
  amount such as 12.345 lb (rounded to hundredths by the server).
- `make test` and `make e2e` share the test database and must run one after the other.
