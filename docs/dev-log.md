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

## Stage 4: AI donation intake  (2026-10-08 16:02 to 16:30 EDT)
- Model: **`us.anthropic.claude-haiku-4-5-20251001-v1:0`** (Claude Haiku 4.5 through its `us.` inference
  profile), set as `BEDROCK_MODEL_ID` in `.env` (and as the default in `.env.example`). Access
  check, in the requested order: Haiku 5.5 (`us.anthropic.claude-haiku-5-5`, also `global.`) is
  listed but returns "not available for this account"; Haiku 4.5 worked; Nova Lite was not tried.
  The first attempts failed because the IAM user had no Bedrock permissions
  (`ListInferenceProfiles` and `InvokeModel` denied) until `AmazonBedrockFullAccess` was attached.
- Built:
  - Backend: `BedrockProvider` over the Converse API (text, PDF document and image blocks;
    forced tool call with a schema generated from Pydantic; 5 s connect and 45 s read timeouts;
    logs model, latency, tokens, outcome); a shared retry policy (one retry across timeouts,
    throttling, 5xx and unusable answers, with the rejection reason sent to the second attempt);
    the extraction prompt; `StorageBackend` with `LocalStorage` (path-safe, atomic writes) and an
    S3 stub; upload checks (extension, real content, 10 MB, text length, Bedrock's smaller PDF and
    image limits, filename cleaning); `.eml` parsing; endpoints `POST/GET /api/donations`,
    `GET /api/donations/{id}`, `POST .../confirm`, `POST .../reject`, `GET /api/donors`;
    migration `0002` (donor chosen during review, `reviewed_by`/`reviewed_at`,
    `original_filename`, two new CHECK constraints).
  - Frontend: Donations page with upload (client-side checks, loading state with Cancel, error
    banner with Try again), filter tabs, empty state, success notices; review screen with an
    editable table (cards on phones), amber "AI unsure (n%)" highlighting under 80%, add and
    remove rows, donor picker or new donor, per-field errors, Confirm and a two-step Reject; a
    Donations link in the coordinator navigation; regenerated API types.
  - Eval: 50 golden manifests (30 `.eml`, 15 `.pdf`, 5 photos) with answer files, `scoring.py`,
    `run_intake_eval.py` (also `--rescore`), `make eval` and `make golden`.
- Tests: written first and seen failing. `make test`: ruff clean, **468 pytest passed** (about 21 s),
  frontend lint, typecheck and build pass. The mocked-LLM tests cover valid JSON; invalid JSON
  then a good retry; invalid twice (502, nothing saved); a timeout then success; two timeouts
  (504, nothing saved, exactly one retry); throttling; access errors (not retried, no AWS details
  leaked); a wrong file type (including `.exe`, double extensions and content that does not match
  the extension); a file over 10 MB and exactly 10 MB; an empty file; an image over the model
  limit (shrunk, original kept); a storage failure (nothing left behind); no items and no lots
  until Confirm; confirm and reject rules (atomic, 409 on a second decision, expired items
  blocked, edited and added rows flagged); roles; storage path safety; provider request shape,
  error mapping and logging; scorer, golden-set integrity (every manifest passes the app's own
  upload validation) and runner. A guard fails any test that creates a boto3 session. I also broke
  the code six ways on purpose (no retry, double confirm allowed, expired items accepted, file
  content not checked, tool call not forced, stored file differing from the upload); each was caught
  by the intended test.
- One real call (golden manifest 003, an email): all 6 items matched the golden answer on every
  field (frozen chicken and turkey came back as protein with frozen storage; 160 kg became
  352.7 lb); 5.2 s, 2,759 tokens in, 1,116 out.
- **Eval (one `make eval` run, 50 manifests, 70 s):** first scoring **92.9%** (1,867 of 2,009
  fields), below the 95% target. After correcting the answer key and scoring the **same saved
  answers** again (no new model calls, prompt unchanged): **98.7%** (1,982 of 2,009), all 287
  items found, 0 extra items, donor name right in 50 of 50, 0 failures, 0 retries. By field:
  name 100%, quantity 100%, unit 100%, category 99.3%, weight 98.3%, expiry 97.9%, storage 95.1%.
  By format: email 99.0%, PDF 98.5%, photo 97.0%. **Token usage: 170,445 in + 53,773 out =
  224,218 total** (about 3,408 in and 1,075 out per manifest, 5.3 s average latency).
- Problems found and fixed:
  - The first eval score exposed a flaw in my answer key: it accepted one name per food, so the
    model's faithful 'UHT milk', 'Popsicles', 'Oatmeal', 'Romaine hearts' and 'Cheddar blocks'
    counted as 16 missed items and 10 wrong names. The key now lists every name a manifest may use.
    That fixed 115 of the 142 wrong fields and revealed 7 real mistakes hidden behind the misses.
    The key was corrected after seeing the result, so the 98.7% is not a blind score; the golden
    set is synthetic and uses the same rules as the prompt. Both numbers are in the report.
  - In the browser, editing a field and then submitting hid that field's error (a cleared server
    error stored as `undefined` overwrote the client error when merged). Fixed in
    `review-form.tsx` and re-checked.
  - The model gave "Expires: AI unsure (0%)" for items whose manifest simply has no date. The
    prompt now says a missing date is high-confidence when the manifest clearly has none.
  - My first draft of the report's scoring note had two wrong numbers (122 fixed and 20 remaining);
    the true figures are 115 and 27. Caught by checking the note against the report and corrected.
  - Test-fixture teardown deleted users that new donations still referenced; the cleanup now
    clears donation tables first. `openapi-typescript` regenerated for the new endpoints.
- Decisions: Haiku 4.5 (Haiku 5.5 not available to the account); forced tool call instead of
  prompt-only JSON (as requested); one shared retry budget; a failed extraction saves nothing;
  rejected donations are kept as an audit record; model output reaches `donation_items` and lots
  only on Confirm; the donor is chosen on review; images over 3.75 MB are shrunk for the model but
  stored unchanged; extraction runs inside the upload request; absent-date confidence wording.
- Real model mistakes seen in the eval (left as follow-ups, because changing the prompt would
  need another paid run to verify): fresh apples and carrots called `ambient` (no default storage
  rule in the prompt, 9 of the 27 wrong fields); UHT milk called `refrigerated` (3) and its
  weights wrong in 3 cases; fresh chicken and ground beef called `frozen` (2); refrigerated 2%
  milk called a beverage (2); "2 boxes" weighed as one box and "20 cases" of eggs as 20 dozen;
  month-only dates resolved to the 1st instead of the last day (2) and a year-less date to a past
  year (2); "5/27/28" read as May 2028 (2). Suggested prompt additions for the Stage 8 quality
  pass: default storage by food, "refrigerated milk is dairy, only shelf-stable milk is a
  beverage", a worked example for boxes and eggs, and one for month-only and year-less dates.
- Not done on purpose: no IAM changes were made by me (the AWS user was configured by the owner);
  the app database still holds the two donations I created while testing the screens, which
  `make seed` clears.

## Stage 5: Demand forecasting  (2026-10-08 16:52 to 17:19 EDT)
- Built:
  - Backend: `app/services/forecasting.py` (censoring correction, features, seasonal-naive baseline,
    three LightGBM quantile models, metrics, rolling-origin backtest); `forecast_runs.py` (reading
    the panel from the database, recording runs, saving models through `StorageBackend`);
    `POST /api/forecasts/run`, `GET /api/forecasts` (pantry, category, week, kind, run filters),
    `GET /api/forecasts/series`, `GET /api/forecasts/runs/latest`; migration `0003` (run kind,
    coverage, backtest start, model key, error message, and CHECK constraints); calendar rules
    moved to `app/services/calendar_rules.py`; `generate_with_truth` added to the generator.
  - Evaluation: `eval/forecast_backtest.py` and `make backtest` (a backtest run saved to the
    database, plus `docs/eval/forecast-backtest.md` with a 19-row leakage table).
  - Frontend: Forecasts page (pantry and category filters, Recharts chart of history, forecasts and
    the P10 to P90 band, optional last-year line, accuracy table with when the backtest ran, run
    button, loading, empty and error states, a table of the numbers) and a Forecasts link.
- Change from the plan (as requested): `POST /api/forecasts/run` trains once and forecasts next week
  only; the 12-origin backtest runs only from `make backtest`.
- Tests: written first and seen failing. `make test`: ruff clean, **591 pytest passed** (123 new),
  frontend lint, typecheck and build pass. Covered: no future data in the features (features
  identical with or without later weeks; a week's own observations replaced with garbage do not move
  its features; a missing week leaves a gap); lags and rolling means on a ramp; weather as last
  week plus a climatology of earlier years; the baseline on tiny fixtures; the censoring correction
  applying only to the exact shortage-report week (thresholds, caps, zero visits, neighbours
  untouched, switch-off); WAPE and coverage arithmetic; P10 <= P50 <= P90; deterministic training;
  a save/load round trip through storage; the backtest scoring the last 12 origins with each fold
  trained only before its week; overwriting the future with garbage changing no earlier prediction;
  the forecasting module never importing the generator or its truth; the API (filters, 401 and 403,
  409 while a run is in progress, a stale run not blocking, 422 on too little history, a model
  failure recorded without leaking details); constraints for the new columns; the generator's output
  unchanged by the refactor (fingerprint pinned).
- **Results (one `make backtest`, 12 weekly origins, 680 series, 8,160 forecasts, 55 s):**
  - WAPE vs observed pounds: **LightGBM 10.7%, baseline 14.5%** (26% lower error).
  - WAPE vs true demand (synthetic only): LightGBM 10.2%, baseline 14.3%.
  - **P10 to P90 coverage: 77.2%** of observed pounds (79.2% of true demand), aim 80%; the average
    interval is 32.5% of the P50 wide.
  - Series under 20% WAPE: 99.9% for LightGBM (679 of 680; the exception is pantry 12 dairy at
    20.9%), 95.4% for the baseline. Median series WAPE 10.5% against 14.2%.
  - Stable across origins (10.2% to 11.1%) and categories (9.7% to 11.2%). In the 244 forecasts
    for weeks with a shortage report the observed WAPE is 17.4% (observed is capped by supply there)
    but 11.6% against true demand.
  - Reruns give identical numbers (training is deterministic).
- **The censoring correction did not measurably help:** 10.2% against true demand with and without
  it, and 11.6% against 11.8% in the shortage weeks. Shortage reports cover only about 3% of
  cells, and the model also has last week's shortage as a feature. The correction is kept (it is
  correct in principle and costs nothing), and the report says plainly that it made no measurable
  difference here.
- **Leakage review:** the 19 checks and the probe on the real data are in the backtest report. I
  injected eight leaks one at a time (lag 1 reading the week itself, rolling means including the
  current week, the week's own weather as a feature, training rows including the forecast week,
  backtest history including the forecast week, a 51-week baseline, an uplift on every week, a
  climatology reading a year ahead): the first run caught seven, and the missed one (training rows
  including the forecast week) was an equivalent mutation, protected by a second guard (the empty
  target). I added a test that exercises the week filter on its own, and all eight are now caught.
  Calls for your review: L7 (school-holiday and benefit flags of the forecast week are used because
  they are scheduled in advance), L8 (`baseline_households` is a constant) and L19 (log transform
  only).
- **Speed (the 20 s rule):** `POST /api/forecasts/run` takes 3.5 s through the Next.js proxy and 3.5 s
  straight to the API; the read endpoints take 7 to 50 ms. Nothing is near 20 s, so I did not
  change the proxy. (Next.js has `experimental.proxyTimeout`, unset here; the bundled docs do not
  describe its default.) Each backtest origin trains in about 4.5 s.
- Problems found and fixed:
  - The first mutation run printed nothing for every case; I did not trust that, found two patterns
    that ruff had reformatted away, and rewrote the harness to print real pytest results.
  - The Forecasts page showed the backtest period as ending a week early (it displayed the last
    training week instead of the last week scored). Added `backtest_end` to the API, with a test.
  - A test that a flat series is forecast at its level failed with the fast 20-tree test settings;
    the cause was under-training (the full settings reproduce the level exactly), so that test now
    uses a more converged configuration.
  - Pandas and the probe used `pantry_id` and `category_id` as both row index and feature columns
    (a `KeyError`), fixed in the tests and the probe.
  - My first attempt to trim test runs from the database silently did nothing (missing `-i` on
    `docker exec`); caught by printing the result, redone and verified.
  - Browser checks with the pane hidden made the chart look stuck. A hidden tab pauses the page's
    scheduled work, so this was my test setup, not the app; confirmed by fronting the tab.
- Decisions: weather limited to last week plus a climatology (decision 1); one-week horizon (2);
  primary metric is WAPE against observed pounds, with the true-demand WAPE secondary and only in
  `eval/` code (3); the forward run is synchronous (changed per your instruction); log-target
  quantile models; fixed hyperparameters; baseline uses observed (uncorrected) pounds; categories are
  ordered produce, dairy, protein, ... in API results.
- Known limits: the data is synthetic; the intervals are a little narrow (77.2%); only 12 origins and
  one seed; a single series' WAPE rests on 12 numbers; no multi-week horizon; no automatic weekly
  schedule yet (the weekly refresh job comes in Stage 7). `make seed` clears the forecast tables, so
  run `make backtest` and **Run forecast** afterwards.
- The app database now holds the latest backtest (run 2) and one forward run (run 7).
- **Leakage review by the project owner (recorded after Stage 5 was committed):** reviewed the three
  judgement calls flagged in `docs/eval/forecast-backtest.md` and **agreed with all three**:
  - **L7:** using the school-holiday and benefit-week flags of the forecast week is acceptable, because
    both are scheduled in advance and so are known at forecast time.
  - **L8:** treating `baseline_households` as a constant is acceptable.
  - **L19:** the log(1 + demand) target transform is acceptable: it has no parameters, so no
    statistic from the test weeks reaches training.
  No change to the forecasting code or the backtest was needed as a result.

## Stage 6: Expiry-aware allocation  (2026-10-08 17:16 to 17:53 EDT; end = commit time, start = previous commit)
- Built:
  - Optimizer `app/services/optimizer.py` (OR-Tools GLOP): tiered demand reward (1.0 per lb to P50,
    0.5 from P50 to P90), urgency bonus for food close to expiry, small distance penalty; lot supply,
    cold and dry capacity and P90 constraints. 23 lots x 85 pantries (about 2,600 variables) solve in
    milliseconds.
  - Current stock: `add_current_inventory` in the generator (own seed, so the pinned history
    fingerprint is unchanged), loaded by `make seed` (24 lots, 435,495 lb for the forecast week).
  - Migration `0004`: run and allocation columns, CHECK constraints (including `decision_fields`),
    audit-log field check and indexes. `allocation_runs` now records week, delivery date, counts,
    reasons by source, model id, tokens and duration.
  - `app/services/allocation_runs.py` (run, approve, edit, reject, bulk approve, write more reasons),
    `allocation_reasons.py` (templates, one batched Bedrock call, validation), the API in
    `app/api/allocations.py`, per-call timeouts in the Bedrock provider.
  - Frontend: Allocations page (status tabs, county and search filters, grouped by pantry, inline edit
    with validation, approve all shown with a confirm dialog, write more AI reasons, AI/Template tags,
    loading, empty and error states), nav link, helpers in `src/lib/allocations.ts`.
  - `eval/allocation_sim.py`, `make simulate`, `docs/eval/allocation-sim.md`.
- Tests written first: optimizer (supply, capacity and P90 never exceeded on random inputs; soonest
  expiring first; nearer pantry first under shortage), current inventory, constraints and migration,
  reasons (validation and fallbacks), the API (permissions, edits logged, rejected lots re-offered,
  over-allocation refused, re-run behaviour, bulk all-or-nothing, reasons fallback, 20 second bound),
  and the simulation on a hand-checkable fixture. Full suite: 736 passed.
- **Your additions:** the plain statement that this data supports the stockout comparison but cannot
  test the spoilage target (spoilage is drawn per lot independent of allocation), and what a pilot
  would measure, is in `docs/eval/allocation-sim.md` and the README.
- **Stockout result (needs your attention):** the simulation does **not** show the 30% stockout
  reduction. Primary setup (Wednesday and Friday deliveries): shortage pantry-weeks 31.3% for the
  manual stand-in against 33.2% for the optimizer (+6%). The optimizer is better with one delivery
  a week (38.9% vs 57.4%) and worse than a manual rule that remembers what it already sent (18.0%).
  62% of the optimizer's short cells were weeks when true demand exceeded P90, which the design
  never ships beyond. My first prototype (single weekly shipment, all of a week's lots
  available at once) showed 31% vs 43%; that setup let a Thursday arrival ship on Wednesday and
  gave the optimizer a clearer win, so I did not use it as primary. I did not tune the optimizer to
  the simulation; the P50 to P90 band reward (0.5) was the one setting chosen after comparing 0, 0.3,
  0.6 and 0.9 on this data, and that is stated in the report.
- Speed: `POST /api/allocations/run` took 7.6 s (5 AI reasons accepted) and 9.3 s (40 of 40 accepted)
  with real Bedrock through the Next.js proxy; reads and decisions are tens of milliseconds. Nothing
  near 20 s.
- Problems found and fixed:
  - A literal "P50 only" objective made shortages worse (65.6% vs 43.2% in the prototype), which led
    to the tiered reward you approved.
  - The first real Bedrock run kept only 5 of 40 reasons: the model invented "surplus" figures and
    differences. The validator rejected them correctly. The prompt now bans arithmetic and the facts
    carry a `coverage` phrase; 40 of 40 passed on the next run.
  - A NULL slipped past the `decision_fields` CHECK; added `final_lbs IS NOT NULL` and fixed the
    migration.
  - An empty-string slice replacement corrupted `llm_provider.py` (16.9 MB); restored from git and
    re-edited with exact-once assertions.
  - My first simulation used one Wednesday delivery, so Thursday and Friday arrivals expired before
    the next run and both policies looked terrible (99.9% vs 82.9%). Added a Friday re-run (as the app
    allows) and show all three schedules in the report.
  - A first version of the report said the optimizer "was not tuned"; that was not true (see above) and
    was corrected before commit.
  - Decimal coordinates broke the haversine in the API (a 500); converted to float, with a test.
- Decisions: nine as approved (tiered reward; AI reasons for 40 rows with a "write more" endpoint;
  seeded current stock; delivery date rule; re-run replaces undecided rows; edit means approved with
  a different amount; capacity and forecast netting of approved rows; simulation design; `ortools`
  dependency). Additions of mine: a second simulated delivery on Friday and the manual-rule variants in
  the report; rejected AI reasons are logged (pantry and text, no other data).
- Known limits: the optimizer never ships beyond P90; pantry capacity is a weekly intake limit, not a
  live storage level; straight-line distance; the simulation's manual rule is an assumption; a run
  makes one Bedrock call (about 5,400 tokens); no weekly schedule yet (Stage 7).
- The app database was reseeded at the end (current stock present, no allocation runs). Run
  `make backtest` (done), **Run forecast**, then **Run allocation**.

## Stage 7: Pantry portal and impact dashboard  (2026-10-08 17:53 to 18:12 EDT; end = commit time, start = previous commit)
- Built:
  - Pantry portal: `/api/pantry/deliveries`, `/api/pantry/shortage-reports` (update on duplicate via
    `ON CONFLICT`, migration `0005`), mobile-first page with delivery cards and a three-tap shortage form.
  - Dashboard: `/api/dashboard/metrics` (households once per pantry-week), Recharts page with date
    presets, a live clock, KPI cards, four time series and a by-category chart and table.
  - Monthly summary: one forced-tool Bedrock call on aggregates only, the shared `number_check` (also
    now used by allocation reasons), admin edit and approve (final, one per month).
  - `POST /api/admin/jobs/weekly-refresh`, `make refresh` (`scripts/refresh.py`), a dashboard button.
- Tests (written first): `test_dashboard_metrics`, `test_shortage_reports`, `test_pantry_portal`,
  `test_summaries`, `test_number_check`, `test_admin_refresh`. Full suite 799 passed; frontend lint,
  typecheck and build pass.
- Browser checks (the five you listed): pantry portal at 375 px with one shortage report submitted;
  dashboard with the 12-week preset; one real summary drafted and approved; one weekly refresh.
- Speed: refresh 13.3 s in the browser and 13.9 s from `make refresh` (forecast 3.9 s, allocation
  10 s). Summary draft about 4 s. Nothing near 20 s.
- Problems found and fixed:
  - The first summary draft passed the number check but called pounds "items" and compared totals
    across months of different length. The check cannot see labels; I tightened the prompt (say
    "pounds", thousands separators, compare only percentages) and kept the human approval. Not re-run
    against Bedrock after the prompt change (you asked for one real draft).
  - The dashboard showed "Loading" on first paint (initial cache key lacked the reload counter).
  - Test teardown: shortage reports and approved summaries reference users and pantries, so the shared
    `people` fixture now clears them first.
- Decisions: the seven as approved. Small additions of mine: the category-level `by_category` rows
  include all eight categories; "stockout %" counts pantry-weeks with a report that also have
  distributions; hand-written summaries store an empty `ai_draft`.
- Known limits: no schedule runs the refresh; deliveries are planned, not confirmed; the dashboard
  summary prompt change is untested against the real model; the demo summary for September 2026 in
  the dev database was approved during the browser check and can be ignored.

## Stage 8: Quality pass  (2026-10-08 18:12 to 18:29 EDT; end = commit time, start = previous commit)
- Built:
  - **Form validation audit.** Login, intake upload, intake review, allocation edit, shortage report,
    summary editor and dashboard date range all had inline client messages and Pydantic checks except
    two gaps: the dashboard range had no client check for more than 260 weeks (added) and the login
    inputs had no length limits (added). `test_input_validation.py` (22 tests) covers bad dates,
    over-long ranges, bad id lists, bad filters, bad bodies and an over-long summary, each a 422 in
    the error envelope with nothing saved.
  - **Responsive pass.** Navigation collapses into a menu below 768 px, every control is at least 44 px
    tall below 1024 px (global CSS rule, nav links sized separately), tables already scroll in their
    container or become cards. Checked with a script on every page at 375, 768 and 1280 px: no
    horizontal overflow anywhere; the first 768 px run found five nav links at 32 px, fixed.
  - **Login lockout** (migration `0006`, `app/auth/throttle.py`): database-backed counter per email and
    per address, 5 and 20 failures in 15 minutes lock for 15 minutes, 429 with `Retry-After`, hashed
    keys, unknown emails counted the same. 12 tests including "a second app instance sees the lock".
  - **Intake prompt fixes** from the Stage 4 follow-up list (default storage by food, milk, weight per
    unit, month-only and year-less dates). The golden key was frozen first and committed alone
    (`76cc202`, `KEY.sha256`, enforced by `make eval` and a test).
  - **Organisation:** README rewritten (problem, features, architecture, setup, every environment
    variable, demo logins, commands, testing, all three evaluations, minimum IAM policy, limitations);
    `.env.example` has a comment on every variable; CLAUDE.md folder tree updated to the real names;
    dead code removed (`summaries.has_data`, four `.gitkeep` files); `test_error_envelope.py` checks
    every route in the OpenAPI schema returns the envelope for logged-out and wrong-role callers.
- **Intake eval, one run (blind to the key, not to the failure modes):** 99.5% (1,999 of 2,009 fields),
  against 92.9% on the first scoring and 98.7% after the key was corrected. All 287 items found,
  244,848 tokens. Remaining ten wrong fields: four month-only dates read as the 1st, one "5/27/28"
  misread, two weights, two storage types (fresh ground beef as frozen, apples as ambient) and one name. The caveats are in the report: the fixes target mistakes
  seen on this same synthetic set.
- Tests: 840 passed (`make test`), frontend lint, typecheck and build pass.
- Problems found and fixed: nav links 32 px at tablet width; shared test fixture left throttle rows
  that would lock later tests (cleared in the `client` fixture); the Stage 6 and 7 headings carried
  invented start and end times, now replaced by commit times.
- Decisions: lockout limits (5 per email, 20 per address, 15 and 15 minutes); the address comes from
  `X-Forwarded-For` with a documented caveat; CLAUDE.md's tree was edited to match the code instead of
  renaming pages.

## Stage 9: Final verification  (2026-10-08 18:29 to 18:35 EDT; end = commit time, start = previous commit)
- Procedure (README, from nothing): stopped both servers, `docker compose down -v` (the database volume
  was deleted), `make db`, `make migrate` (6 migrations), `make seed`, `make backtest`, `make test`,
  `make dev`. Then in the browser: logged out redirect with `next`, empty-form validation, coordinator
  login through the form, **Run forecast** (3.8 s), a real manifest uploaded, reviewed and confirmed
  (6 lots, 1,828 lb), **Run allocation** (720 shipments, 9.2 s), admin dashboard with charts, a real AI
  summary draft, **Run weekly refresh** (12.8 s), pantry manager portal at 375 px with deliveries, a
  shortage report and its update (201 then 200 `updated: true`), and 403 for the manager on the
  dashboard and allocations.
- Tests: `make test` on the clean database: 840 passed; frontend lint, typecheck and build pass.
- Console and API checks: API log for the whole session: 0 errors, 0 warnings. Browser console: no new
  errors from the app. The only errors were `ws://localhost:3000/_next/hmr` failures and four 404s
  logged while the servers were stopped or restarting (the open dashboard tab refetching), and two
  deliberate 403s from my permission probes.
- Problems found and fixed:
  - After **Run allocation** the page flashed "Nothing to review yet" under the "Calculating" button while
    it reloaded 720 rows. Root cause: the empty state ignored that a run was in progress. Fix: hidden
    while a run is in flight.
  - The new summary prompt was verified against the real model: thousands separators and "pounds" are
    now used (the Stage 7 draft called pounds "items").
- Not fixed: the Stage 8 prompt still reads month-only dates as the 1st in four cases (see the intake
  report).

## Stage 10: Testing checklist and E2E coverage  (2026-10-11 00:54 to 08:48 EDT; end = commit time)
- Numbering: the deployment stage (App Runner) never happened and is deferred, so this is Stage 10; the
  later assignment 5.4 stages are 11 to 14.
- Built:
  - `docs/testing/checklist.md`: every feature, button, form field, dialog and error state, page by page
    and role by role (logged out, coordinator, admin, pantry manager). Source of truth is
    `backend/scripts/testing_checklist.py`; `make e2e` regenerates the file with each row's tests and
    result. `tests/test_testing_checklist.py` checks IDs are unique, every cited pytest test exists and
    every E2E test cites a real row.
  - Playwright E2E in `frontend/e2e` (`make e2e`): Chromium at 375, 768 and 1280 px plus WebKit at 1280.
    It runs against its own API (port 8101, the real app on the TEST database with a scripted mock AI, a
    throwaway upload folder and a pinned date) and a production `next start` on port 3101. The dev app and
    real Bedrock are untouched. `backend/scripts/e2e_server.py` holds the mock AI and a reset route;
    `tests/test_e2e_isolation.py` proves the normal app cannot load them (no mention under `app/`, no
    routes, real Bedrock provider, refuses to start without `E2E_MODE=1` or on a non-test database).
  - axe-core scans of every page per role and width: `docs/testing/a11y-report.md` (report only, no fixes).
  - Known bugs are E2E tests marked `test.fail()` with the bug ID in the title, so `make e2e` is green and
    Playwright flags the test when the bug is fixed. `docs/testing/bugs.md` lists 9 bugs.
- Tests: `make test`: 851 passed (538 test functions; the 851 collected cases are more because parametrized
  tests run once per parameter). `make e2e`: 628 test runs (621 passed, of which 42 are known-bug runs;
  0 failed, 7 skipped by design because they only apply at some widths). Checklist: 185 items, 182 automated.
- Problems found and fixed (in the tests and harness, not the app):
  - Clicks and typing right after load were lost because React had not hydrated; added an `open()` helper
    that waits for the network to go quiet.
  - `make test` and `make e2e` share the test database; pytest rebuilds it, so e2e setup always reseeds.
  - Test donors leaked between tests and changed the review page's default donor; the reset route now
    deletes them.
  - A hidden menu button made a tap-target test wait 30 s; it now clicks only when visible.
  - A laptop sleep during a long run produced a false timeout; the final run used `caffeinate`.
  - The checklist test misread templated test titles and bug tags; fixed.
- Bugs found in the app and NOT fixed (details in `docs/testing/bugs.md`): ids above 2,147,483,647 return
  500 (BUG-01), huge `pantry_id` on the series route (02), year 9999 week and dashboard dates (03, 04),
  month `0000-01` (05), a NUL character in text returns 500 including on the logged-out login route (06),
  Donations page links under 44 px (07), HTTP 200 for a missing record in the app shell (08), the
  donation list shows only the newest 100 of 3,626 (09).
- Decisions: the failing-by-design tests use `test.fail()` as you asked; one worker because of the single
  shared database; the E2E mock AI is a separate module under `scripts/`, never under `app/`.
