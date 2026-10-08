# Dev log

## Stage 1: Scaffold  (2026-10-08 15:01 to 15:05 EDT)
- Built: git repo with `.env` ignored before the first commit; folder tree from CLAUDE.md;
  `docker-compose.yml` (Postgres 16, one container, databases `pantrypulse` and
  `pantrypulse_test` created by an init script); FastAPI app factory with `GET /api/health`
  (runs `SELECT 1`, returns 503 in the error envelope when the database is down), JSON logging
  with request ids, one error envelope for HTTP, validation, `ApiError` and unhandled errors;
  Next.js 16 (App Router, TypeScript strict, Tailwind 4) with an `/api/*` rewrite to FastAPI and a
  status page; `.env.example`; Makefile (`setup`, `db`, `dev`, `test` implemented; `migrate`,
  `seed`, `eval`, `refresh` are placeholders for later stages); `docs/architecture.md`
  (including the category vs storage_type rule) and a short README.
- Tests: tests written first and seen failing (import error). `make test`: ruff clean, pytest
  12 passed, frontend lint + typecheck + production build pass. Verified by hand: `make setup`,
  `make db`, `make dev`; `curl localhost:3000/api/health` returns
  `{"status":"ok","database":"ok"}`, matching the direct call on :8000.
- Problems found and fixed:
  - `make dev` left uvicorn and Next.js running after Ctrl-C. Root cause: the trap killed the
    `( ... ) &` wrapper subshells, not the servers inside them. Fix: `exec` inside each subshell
    so the job is the server process. Re-verified with SIGINT to the process group: both ports
    freed.
  - pytest warned that `httpx` is deprecated for Starlette's TestClient. Fix: use `httpx2`.
  - Ruff import sorting treated `app` as third-party in tests. Fix: `known-first-party`.
- Decisions: Python 3.13 in `backend/.venv`; `uvicorn --factory` so settings load at startup, not
  import; no ports or password defaults in code, so `.env` stays the single source; Postgres bound
  to 127.0.0.1 only; accepted `X-Request-ID` only if it matches `[A-Za-z0-9._-]{1,64}`; no
  frontend unit tests (lint, typecheck, build only); `make migrate/seed/eval/refresh` print a
  "not implemented yet" message and exit 0 until their stages.

## Stage 2: Database, data models and synthetic data  (2026-10-08 15:16 to 15:25 EDT)
- Built: SQLAlchemy 2.x models for all 15 tables in CLAUDE.md plus `weekly_context`, with foreign
  keys, NOT NULL, CHECK and unique constraints and a naming convention; Alembic set up with one
  reviewed migration (`0001`) that also inserts the 8 fixed categories; argon2 password helper;
  `scripts/generate_synthetic_data.py` (fixed seed, 85 pantries, 6 fictional counties, 8
  categories, 156 weeks, synthetic weather / school holidays / benefit weeks, about 1 in 4
  pantries short each week, about 12% perishable spoilage); `scripts/seed.py` (truncate and
  reload, three demo users, demo passwords from `.env` only, refuses any database but the app
  database); real `make migrate` and `make seed`; docs in `architecture.md` and the README.
- Tests: written first and seen failing (import errors). `make test`: ruff clean, 125 pytest
  passed (about 9 s), frontend lint, typecheck and build pass. 75 cases prove the database
  rejects bad data (negative or zero quantities, unknown categories, bad enums, non-Monday weeks,
  duplicates, unordered quantiles, half-decided allocations, unapproved summaries) plus
  positive controls; migration tests check upgrade, downgrade and model/migration drift;
  generator tests check reproducibility (same seed gives the same hash, a different seed does
  not) and the ranges below; seed tests load into the test database and check counts, users,
  hashed passwords, sequences, and the safety guards.
- Baseline the seeded data produces (recomputed with SQL, matches the generator):
  - Rows: pantries 85, weekly_context 936, donors 22, donations 3,607, donation_items 4,088,
    inventory_lots 4,088, distributions 106,080, shortage_reports 3,752, users 3, categories 8;
    the forecast, allocation and summary tables are empty until their stages.
  - Perishable spoilage 12.2% (bakery 14.7, produce 14.0, dairy 11.0, protein 9.1).
  - Weekly stockout rate: 25.9% of pantry-weeks have at least one shortage report (about 22 of
    85 pantries a week, range 4 to 53); 3.5% of pantry-category-weeks have one.
  - 80.3% of shortage reports are protein (38.7%) or produce (41.6%).
- Problems found and fixed:
  - First generator run was far off target: 78% of pantry-weeks short and only 47% of reports in
    protein or produce. Cause: allocation noise of 0.25 made about a third of every category
    fall under 90% of demand. Fix: three small parameter sweeps (noise 0.15, supply ratio near
    1.05 for produce and protein and 1.2 or more elsewhere, lower report odds for the other
    categories, slightly higher spoilage rates). Result above.
  - One rejection test passed for the wrong reason: "allocation status unknown" was blocked by
    the decided-by/at rule, not the status list. Found by printing which constraint rejects each
    of the 75 cases; the row now fills in the decision fields so only the status check can fire.
  - Review caught a gap before it shipped: a draft monthly summary with an approver but no final
    text satisfied the approval rule. Added `draft_not_approved`.
  - The censoring test compared pounds per household across categories, which mixes category
    sizes. It now compares within each category.
  - `make seed` printed its missing-password error twice. Removed the redundant handler; it now
    prints once and exits with status 1.
  - Alembic warned about `prepend_sys_path`; set `path_separator = os`.
- Decisions: Postgres enums are CHECK constraints on text columns; the 8 categories are
  inserted by the migration, so `make seed` never truncates them; ids are explicit in the
  generated data and sequences are reset after loading; `frozen` is not a perishable category;
  `distributions.households` repeats across a pantry-week's category rows; historical donations
  use `source_type = 'historical'`; the six counties are fictional; surplus supply is assumed to
  go to other agencies; demo emails use `example.org`; the shortage-report probability depends on
  the pantry and category; the baseline period is the full 3 years.

## Stage 3: Authentication  (2026-10-08 15:29 to 15:36 EDT)
- Built:
  - Backend: login, logout and `GET /api/auth/me` with a JWT in an httpOnly `SameSite=Lax`
    cookie (8 hours, argon2 hashes from `app/auth/passwords.py`); `current_user`,
    `require_roles` and `require_coordinator` dependencies; `GET /api/pantries` (coordinator and
    admin) and `GET /api/pantries/{id}` (a pantry manager may only read their own); a startup
    check that `JWT_SECRET` is at least 32 characters; `COOKIE_SECURE` and `SESSION_HOURS`
    settings.
  - Frontend: login page with client-side validation, inline errors and a loading state; role-based
    navigation; server-side guards that redirect logged-out users (keeping `next`) and wrong-role
    users; `src/proxy.ts` for a real redirect before render when there is no cookie; a logout
    button; a pantries page for coordinators and admins and a "my pantry" page for managers;
    loading and error screens; a typed API client generated from OpenAPI (`make api-types`), with
    a test that fails if the committed `openapi.json` drifts from the API.
- Tests: written first and seen failing. `make test`: ruff clean, 185 pytest passed (60 new),
  frontend lint, typecheck and build pass. Covered: a wrong password returns 401 and an unknown
  email gets an identical response; logged-out requests return 401; a pantry manager calling a
  coordinator route gets 403; a manager reading another pantry gets 403 (also for ids that do not
  exist); expired, tampered, wrong-secret, other-algorithm and unsigned (`alg: none`) tokens are
  rejected; deactivated users and role changes apply on the next request; cookie flags; logs never
  contain passwords or failed-login emails; startup rejects a weak secret.
  I also broke the code five ways on purpose (accept other algorithms, drop the role check, let
  managers read any pantry, keep inactive users logged in, skip the password check for unknown
  emails) and each was caught by the intended test.
- Browser check (built-in browser pane, local dev server): empty and malformed submissions show
  inline errors; a wrong password shows "Incorrect email or password."; manager login lands on
  Pantry 14 and `/coordinator`, `/login` and `/` all redirect them to `/pantry`; in the browser
  the API gives the manager 403 for the list, 403 for another pantry, 403 for a missing id and
  200 for their own; the cookie is not readable from JavaScript; logout returns to `/login` and
  `/api/auth/me` is then 401; a coordinator logging in from a `next=/pantry` link lands on
  `/coordinator` with all 85 pantries; the pages fit 375 px with no horizontal overflow. The
  `?next=` guard was run against 15 inputs including `//evil.example.com`, backslashes, newline
  injection and `javascript:` URLs, all handled.
- Problems found and fixed:
  - After a failed login focus did not return to the password field: the inputs were `disabled`
    while submitting and `focus()` ran before React re-enabled them. They are now `readOnly`.
  - A logged-out request for `/coordinator` returned 200 because the redirect streamed behind the
    loading screen (a flash of skeleton, no data leaked). Added `src/proxy.ts` for a real 307.
  - `openapi-typescript` needs TypeScript 5 and Stage 1 had installed 6; pinned TypeScript to
    `^5.9`.
  - ruff flagged FastAPI's `Depends(...)` defaults (B008); configured it as an immutable call.
- Decisions: PyJWT with HS256; the role is read from the database on every request, not stored
  in the token; unknown email, wrong password and inactive user are indistinguishable; the cookie
  is `Secure` only when `COOKIE_SECURE=true`; no `email-validator` dependency (basic format check,
  lowercased and trimmed); admin counts as a coordinator; navigation lists only pages that exist;
  the proxy only checks that a cookie exists, the pages and API decide the rest; `AGENTS.md` that
  Next.js generated in `frontend/` (committed in Stage 1) is left as is.
- **Deferred to Stage 8:** login lockout / rate limiting. It needs a database-backed counter of
  failed attempts per email and per IP (no in-memory state, per CLAUDE.md rule 4), with a clear
  message and a tested reset. Until then failed logins are only logged (reason and request id,
  no email or password).
- Known limitation (also in the README): logout clears the cookie but cannot revoke a token that
  was already copied; it expires after 8 hours. A `token_version` column or sessions table would
  fix that.
