# Bugs found in Stage 10 (testing) and fixed in Stage 11

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
