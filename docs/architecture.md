# PantryPulse architecture

Local build of the system described in `spec-5.2.md`. `CLAUDE.md` is the build contract and wins
wherever it differs from the spec.

```
Browser ──> Next.js :3000 ── rewrites /api/* ──> FastAPI :8000 ──> Postgres 16 :5433 (Docker)
                                                     ├──> Amazon Bedrock (Stage 4)
                                                     └──> StorageBackend (LocalStorage now, S3 later)
```

- The browser talks to one origin. Next.js proxies `/api/*` to FastAPI, so there is no CORS setup
  and the auth cookie (Stage 3) is first-party.
- Ports and credentials are defined once in the root `.env`. The Makefile exports them to both
  processes; the API reads them through `app/config.py`, Next.js through `API_PORT`.
- One Postgres container holds two databases: `pantrypulse` and `pantrypulse_test`. Tests only
  ever touch the test database.
- The API is stateless: no in-process caches of database data.
- Every API error uses one envelope: `{"error": {"code", "message", "details"}}`.
- Logs are JSON, one line per request with `request_id`, `method`, `route`, `status` and
  `duration_ms`. The request id is returned in the `X-Request-ID` header.

## Decisions on points the spec leaves open

### Category versus storage type

`category` is the **food type**. `storage_type` carries the **temperature**.

- The 8 fixed categories are: produce, dairy, protein, bakery, frozen, canned, dry_goods, beverages.
- `storage_type` is one of: ambient, refrigerated, frozen.
- Frozen chicken is category `protein` with storage type `frozen`.
- The `frozen` category is used only for frozen items that fit no other category, such as frozen
  meals.
- Capacity checks (cold and dry storage per pantry) use `storage_type`, never `category`.

### Other definitions

- **Stockout:** a shortage report for a pantry, category and week.
- **Distance:** haversine distance between pantry and warehouse (or pantry-to-pantry) from
  latitude and longitude.
- **Warehouse:** one location, central to the six counties.
- **Weather and school holidays:** synthetic, generated with a fixed seed. The README says so.
- **Weekly refresh:** `POST /api/admin/jobs/weekly-refresh` requires the `admin` role.
- **Bedrock:** credentials come from the AWS CLI profile `pantrypulse` in `us-east-1`. The model ID
  is set in Stage 4. Tests always use a mocked provider and never call Bedrock; the running app
  always uses real Bedrock.

## Data model (Stage 2)

Sixteen tables, all created by Alembic migration `0001`. Constraints live in the database, not
only in Python: foreign keys (`ON DELETE RESTRICT` unless a child is meaningless without its
parent), NOT NULL, CHECK and unique constraints. Enumerations are text columns with CHECK
constraints rather than Postgres enum types, which are awkward to migrate.

| Area | Tables |
| --- | --- |
| People | `users`, `pantries` |
| Reference | `categories` (the 8 fixed rows are inserted by the migration), `donors` |
| Intake and stock | `donations`, `donation_items`, `inventory_lots` |
| History | `distributions`, `shortage_reports`, `weekly_context` |
| Forecasting | `forecast_runs`, `forecasts` |
| Allocation | `allocation_runs`, `allocations`, `allocation_edits` |
| Reporting | `monthly_summaries` |

Rules the database enforces (each has a test in `tests/test_models_constraints.py`):

- Quantities and weights are positive; a lot's `remaining_lbs + expired_lbs` never exceeds
  `received_lbs`.
- Forecast quantiles are ordered `p10 <= p50 <= p90`.
- Every `week_start` is a Monday; one row per pantry, category and week in `distributions`,
  `shortage_reports` and (per run) `forecasts`.
- A `pantry_manager` has a pantry; no other role does.
- An allocation is either `proposed` (no decider, no timestamp) or decided (both set).
- A monthly summary is `approved` only with an approver, a timestamp and final text.

Decisions beyond the spec:

- `weekly_context` (county, week, temperature, precipitation, school holiday, benefit week)
  stores the forecast features that are not in the minimum table list in CLAUDE.md.
- `distributions.households` is the number of households the pantry served that week, so it is
  identical on every category row of that pantry-week. Dashboard totals must count it once per
  pantry-week, not sum it across categories.
- Historical stock is stored like real intake: `donations.source_type = 'historical'`, no raw
  LLM output, one `donation_items` row per `inventory_lots` row.
- `frozen` is not counted as a perishable category (see the category rule above), so
  "perishable" means produce, dairy, protein and bakery. About half of received pounds.
- **Spoilage** = `expired_lbs / received_lbs` over perishable lots.
- **Weekly stockout rate** is reported two ways: the share of pantries with at least one
  shortage report in a week, and the share of pantry-category-weeks with a report.

## Synthetic data

`backend/scripts/generate_synthetic_data.py` is a pure function of its seed (default 515), so
the same seed always gives the same rows (`fingerprint()` hashes the output; a test checks it).
Weather, school holidays and benefit weeks are **synthetic**, not real county data. The six
counties are fictional.

Generation order: latent weekly demand per pantry and category, then warehouse supply as lots
(perishable lots lose part of their weight to expiry), then a deliberately rough manual
allocation, then `distributed = min(demand, allocation)`. Because recorded distributions are
capped by supply they are **censored**, which is what Stage 5's demand correction has to undo.
A pantry that received under 90% of its demand files a shortage report with some probability,
more often for protein and produce.

Calibrated baseline (seed 515, 156 weeks ending 2026-09-28, 85 pantries):

| Measure | Target | Result |
| --- | --- | --- |
| Perishable spoilage | about 12% | 12.2% |
| Pantry-weeks with a shortage report | about 1 in 4 | 25.9% (about 22 of 85 pantries a week) |
| Pantry-category-weeks with a report | n/a | 3.5% |
| Shortage reports in protein or produce | weighted toward them | 80.3% |
| Households served per month | about 40,000 | 39,999 |

Surplus supply beyond demand is assumed to go to other agencies. The tuning constants sit at the
top of the generator; tests assert ranges around the targets, not exact values.

## Seeding

`make seed` truncates every table except `categories` and `alembic_version`, loads the generated
history with explicit ids, resets the id sequences, and creates three demo users (coordinator,
admin, and a pantry manager for Pantry 14). It refuses to run against any database other than
`POSTGRES_DB`, and fails with a clear message if a `DEMO_*_PASSWORD` is missing from `.env`.
Passwords are stored as argon2 hashes.

## Authentication (Stage 3)

- `POST /api/auth/login` checks the email and argon2 password hash and sets a signed JWT
  (HS256, PyJWT) in an httpOnly, `SameSite=Lax` cookie named `pp_session`. The response body
  carries the user, never the token. `POST /api/auth/logout` clears the cookie.
  `GET /api/auth/me` returns the current user.
- The token holds only the user id and issue/expiry times (8 hours, `SESSION_HOURS`). The role
  is **not** in the token: every request reloads the user, so a role change or deactivation
  applies on the next request.
- Every login failure (unknown email, wrong password, inactive user) returns the same 401
  `invalid_credentials` response, and a password hash is verified even for unknown emails so the
  timing does not reveal which emails exist. Logs record the reason but never the email or
  password.
- Roles are FastAPI dependencies in `app/auth/dependencies.py`: `current_user` (401),
  `require_roles(...)` (403) and `require_coordinator` (coordinator or admin; admin is a superset
  of coordinator, per the role table in CLAUDE.md).
- `GET /api/pantries` is for coordinator and admin. `GET /api/pantries/{id}` lets a pantry
  manager read only their own pantry; any other id, including one that does not exist, is 403 so
  the response does not reveal which pantries exist.
- The API refuses to start unless `JWT_SECRET` is at least 32 characters. Set `COOKIE_SECURE=true`
  when serving over https.

Frontend: server components ask `/api/auth/me` (forwarding the cookie) and redirect logged-out
users to `/login?next=...` and wrong-role users to their own home. `src/proxy.ts` adds a real
redirect before render for visitors with no cookie at all. These guards decide what to show; the
API enforces the rules. The `next` value is only honoured for same-site paths (`lib/safe-next.ts`).
The browser's API types are generated from the app's OpenAPI document (`make api-types`); a test
fails if the committed `openapi.json` no longer matches the API.

## AI donation intake (Stage 4)

```
upload (pdf/png/jpg/webp/txt/eml, <= 10 MB)
  -> checks: extension, real file content, size, text length   (nothing is sent to the model yet)
  -> Bedrock Converse: forced tool call `record_donation_items`, schema generated from Pydantic
  -> Pydantic validation; one retry (shared budget) if the answer is unusable
  -> StorageBackend.put(file) + a `pending_review` donation holding the raw output as JSONB
  -> coordinator reviews and edits; Confirm creates donation_items + one inventory_lot per item
     (Reject creates nothing)
```

- **Provider** (`app/ai/llm_provider.py`): boto3 `bedrock-runtime` built lazily from the
  `AWS_PROFILE` profile (no keys in `.env`), 5 s connect and 45 s read timeouts, temperature 0.
  The running app always uses real Bedrock; tests inject a scripted fake and a guard fails any
  test that creates a boto3 session. Each call logs model, latency, input and output tokens and
  outcome, never the manifest.
- **Retry policy** (`run_with_retry`): timeouts, throttling, 5xx errors and unusable answers
  share one budget of two attempts with backoff. The second attempt is told why the first was
  rejected. Access, validation and configuration errors are not retried.
- **Structured output**: the model must call one tool whose input schema is
  `DonationExtraction.model_json_schema()` (references inlined). Each item has name, category,
  quantity, unit, estimated weight in lb, expiry date, storage type and a 0 to 1 confidence per
  field. The prompt (`app/ai/prompts/extract_donation.md`) states the category rule from this
  document, how weights and dates are worked out, and that the manifest is untrusted data.
  Text is wrapped in `<manifest>` tags and a closing tag inside it is neutralised.
- **Rule 9** (model output never writes without confirmation): extraction stores only the raw
  output on a `pending_review` donation (`raw_llm_output` = tool input, parsed result, token usage
  and attempts). The review screen reads items from that JSONB. `donation_items` and
  `inventory_lots` are created only by Confirm, from the rows the coordinator submitted, in one
  transaction. A row is marked `edited` if it differs from what the model returned or was added by
  hand; untouched rows keep the model's confidence.
- **Failure leaves nothing behind**: an invalid file, an unusable answer, a timeout or a storage
  failure saves no donation and no file. The browser keeps the chosen file for "Try again".
- **Reject** adds nothing to inventory. The donation, its file and the model output stay as an
  audit record with status `rejected`, `reviewed_by` and `reviewed_at`.
- **Size limits**: 10 MB per upload, inclusive. Bedrock's inline limits are smaller, so images
  over 3.75 MB are shrunk to JPEG for the model (the original is what is stored) and PDFs over
  4.5 MB are refused with a readable message. Text over 100,000 characters is refused.
- **Review rules**: an item that expires before today blocks Confirm; a perishable with no
  expiry date only shows a warning. A donor is chosen from existing donors or created by name
  (matched case-insensitively), and is required to confirm.
- **Errors** use the usual envelope. Codes: `unsupported_file_type` 415, `invalid_file_content`
  415, `file_too_large` 413, `file_too_large_for_ai` 413, `empty_file` 422, `no_items_found` 422,
  `ai_invalid_output` 502, `ai_unavailable` 502, `ai_timeout` 504, `ai_busy` 503,
  `ai_not_configured` 503, `donation_not_pending` 409. AWS error details are logged, never shown.

### Intake eval

`backend/eval/golden/` holds 50 synthetic manifests (30 `.eml`, 15 `.pdf`, 5 photo-style
`.jpg`/`.png`), each with an `expected.json`. They are generated from a fixed seed by
`eval/make_golden_set.py`, and cover the hard cases: frozen protein, frozen meals and frozen
vegetables, kilograms, pallets, relative dates ("use within 5 days"), month-only dates, items
with no date, non-food lines, "we will NOT send" lines and prompt-injection text.
`make eval` runs them through the same code as the upload endpoint, scores seven fields per item
(see `eval/scoring.py`) and writes `docs/eval/intake-eval.md`. An item may be printed under
several names, so the answer key lists every accepted name. `python -m eval.run_intake_eval
--rescore` scores saved answers again without calling the model.

## Demand forecasting (Stage 5)

One LightGBM model covers every pantry (85) and food category (8): 680 series. It forecasts next
week's demand in pounds as three quantiles (P10, P50, P90), and a seasonal-naive baseline
(the same week last year, as observed) is kept for comparison. Code: `app/services/forecasting.py`
(pure modelling), `app/services/forecast_runs.py` (reading the data and saving runs),
`app/api/forecasts.py`, and `eval/forecast_backtest.py` (the backtest and its report).

- **Two kinds of run** (`forecast_runs.kind`):
  - `forward`: trains once on all history and writes next week's forecast (680 rows). Started by
    `POST /api/forecasts/run`; takes about 3.5 seconds, so it is a normal request.
  - `backtest`: 12 rolling origins, started only by `make backtest` (about a minute). It stores its
    accuracy on the run (WAPE for both models, interval coverage, the weeks scored) and the 8,160
    forecasts it made, so the Forecasts page can show them. A run is recorded as `running` before
    any work starts and a second forward run is refused (409) while one is fresh; a `running` row
    older than 10 minutes is treated as crashed.
- **Training target and censored demand.** What a pantry hands out is capped by what it received,
  so in a week it ran short the observed pounds under-record demand. Learning from them would teach
  the model to forecast scarcity. For a pantry, category and week with a shortage report, the
  target is raised: `shortfall = min(0.5, max(prior[severity], households_turned_away /
  households_visiting))`, `demand = observed / (1 - shortfall)`, with priors 10% / 25% / 50% for
  severity 1 / 2 / 3. Weeks without a report are left as observed (so unreported shortages still
  bias the target downward). The constants are assumptions. The correction is keyed on the exact
  (pantry, category, week), so it cannot spread to neighbouring weeks.
- **Features** (21), all known at the start of the week being forecast: demand lags 1 to 4 and 52
  and rolling means over 4 and 12 weeks, last week's household visits and shortage history, last
  week's weather and a climatology (the same week one and two years earlier), week of year,
  school-holiday and benefit-week flags, baseline households, and the pantry and category ids. The
  weather of the forecast week itself is deliberately not used: only a forecast of it would exist.
  The two calendar flags are scheduled in advance, so they are allowed; for weeks that have no
  stored row they come from `app/services/calendar_rules.py` (stand-ins for real school and
  benefit calendars, shared with the data generator).
- **Models.** Three LightGBM quantile models on `log(1 + demand)` (P50 is the median, which is
  what WAPE rewards). Predictions are un-logged, clipped at 0 and sorted so P10 <= P50 <= P90.
  Hyperparameters are fixed in `ForecastConfig` before any backtest (300 trees, learning rate 0.05,
  31 leaves) and never tuned on the backtest weeks. Model files are written through
  `StorageBackend` to `forecasts/run-{id}/` (`p10.txt`, `p50.txt`, `p90.txt`, `meta.json`).
- **No future data.** `build_frame` is only ever handed weeks before the forecast week and adds one
  empty row per series for it; every feature is a lag of at least one week, a rolling window over
  an already-shifted series, or calendar and static data. `docs/eval/forecast-backtest.md` lists
  every leakage check (19 of them) with the test that enforces it, and a probe on the real data.
- **The simulator's true demand** (`generate_with_truth`) is used in exactly one place: the
  backtest script, after the backtest, to report a second WAPE against what demand really was.
  The forecasting module does not import the generator; tests check that.
- **API** (coordinator and admin): `POST /api/forecasts/run`; `GET /api/forecasts` with
  `pantry_id`, `category`, `week_start`, `kind` and `run_id` filters (each row also carries the
  actual pounds once the week has happened); `GET /api/forecasts/series` (what the chart needs:
  recent actuals, backtest forecasts and next week's forecast, plus the accuracy for that series);
  `GET /api/forecasts/runs/latest` (the latest backtest and forward run). Errors:
  `not_enough_history` 422, `forecast_in_progress` 409, `forecast_failed` 500 (the cause is stored
  on the run, not shown).

## Expiry-aware allocation (Stage 6)

- **The optimizer** (`app/services/optimizer.py`) is a linear program solved with OR-Tools GLOP.
  Variable: pounds of lot `l` sent to pantry `p` for the forecast week. Constraints: each lot ships
  at most what remains; a pantry's refrigerated and frozen intake is at most its cold capacity and
  its ambient intake at most its dry capacity; each pantry and category receives at most its P90.
  Objective, in order of weight: demand met (1.0 per lb up to P50, 0.5 per lb from P50 to P90), an
  urgency bonus of 0.20 x max(0, 1 - days left / 10) per lb, and a distance penalty of 0.0005 per
  lb per mile from the warehouse. The credit for the P50 to P90 band exists because aiming at P50
  alone leaves a pantry short about half the time. Lots that expire before the delivery date are
  excluded and reported; shipments are rounded down to hundredths and anything under 1 lb is
  dropped. About 2,600 variables solve in milliseconds.
- **Delivery date** is `min(max(forecast week start, today), that week's Friday)`.
- **Inputs on a re-run.** Forecasts and each pantry's cold and dry capacity are net of rows already
  approved for the week; lots' `remaining_lbs` already has approved pounds taken out. Proposed rows
  from an earlier run of the same week are deleted first; decided rows stay.
- **Deciding.** Approve, edit (status `edited`, the new amount) and reject lock the lots involved in
  id order, then the rows, so concurrent requests cannot over-allocate a lot or deadlock. Bulk
  approve is all-or-nothing and checks each lot's total. Conflicts return 409 `allocation_decided`,
  `lot_short` or `lot_expired`; a bad amount is a 422 `validation_error`. Status changes, amount
  changes and notes are written to `allocation_edits` (`field` is `status`, `final_lbs` or `note`).
  The database also enforces the shape of a decision (`decision_fields`): proposed rows carry no
  final amount, approved or edited rows carry a positive amount and a delivery date.
- **Reasons** (`app/services/allocation_reasons.py`): every row first gets a template reason. One
  Bedrock Converse call (forced tool use, 10 second timeout, no retry) rewrites the 40 largest rows;
  at about 35 output tokens a row, all ~700 rows would take minutes, which would break the 20 second
  limit. The model is given facts and a plain-words `coverage` field and must not calculate; a
  reason is kept only if it names the pantry, is one line of at most 160 characters, and every
  number in it appears in that row's facts. Tokens, duration and counts are stored on the run.
- **API** (coordinator and admin; pantry managers get 403): `POST /api/allocations/run`,
  `GET /api/allocations` (rows for the latest run's week, optional `status`, with a summary),
  `GET /api/allocations/runs/latest`, `POST /api/allocations/{id}/approve|reject|edit`,
  `POST /api/allocations/bulk-approve`, `POST /api/allocations/runs/{id}/reasons`. Errors:
  `no_forecast` and `no_inventory` (422), `optimizer_failed` (500).
- **Current stock.** The generator (`add_current_inventory`, its own fixed seed so the pinned
  history does not change) adds about two dozen available lots sized to demand, perishables
  expiring 6 to 13 days after the forecast Monday. `make seed` loads them as confirmed donations.
- **Simulation** (`eval/allocation_sim.py`): replays the last 12 backtest weeks; the report states
  that spoilage cannot be tested on this data.

## Pantry portal, dashboard and weekly refresh (Stage 7)

- **Pantry portal** (`app/api/pantry_portal.py`, pantry managers only): `GET /api/pantry/deliveries`
  (approved and edited allocations for the manager's own pantry; upcoming from today, recent for the
  last 7 days), `GET` and `POST /api/pantry/shortage-reports`. The pantry always comes from the
  logged-in user, never the request. The week is the Monday of the server's today. A report is an
  `INSERT ... ON CONFLICT (pantry, category, week) DO UPDATE` (migration `0005` adds `updated_at`);
  201 for a new report and 200 with `updated: true` for a replacement.
- **Dashboard** (`app/services/dashboard.py`, admin only): `GET /api/dashboard/metrics?start&end`
  (dates snap to Mondays; default is the last 26 weeks that have data; at most 260 weeks).
  Households: `MAX(households)` per pantry-week, then summed. Spoilage: perishable lots by received
  week. Stockout %: pantry-weeks with a report over pantry-weeks with distributions.
- **Monthly summary** (`app/services/summaries.py`, prompt in `app/ai/prompts/monthly_summary.md`):
  aggregates (this month and the last, plus per-category) are the only input. One forced tool call,
  15 s, no retry in the request. `app/services/number_check.py` (shared with allocation reasons)
  rejects any number not in the aggregates (+/-1 for 20 and over, 0.06 below). Drafts are rows in
  `monthly_summaries` with status `draft`; approval stores the admin's final text and cannot be
  repeated (409). Errors: `summary_failed` and `summary_numbers_mismatch` (502), `no_data` (422).
- **Weekly refresh** (`POST /api/admin/jobs/weekly-refresh`, `app/jobs/weekly_refresh.py`): forward
  forecast, then allocation. A forecast failure returns that error and runs nothing else; an
  allocation failure returns `refresh_partial` with the saved forecast run id.

## Login lockout (Stage 8)

`app/auth/throttle.py` counts failed logins in the `login_throttle` table (migration `0006`), keyed
by SHA-256 of `email:<address>` and `ip:<address>`, so no email or address is stored. Five failures
for an email or 20 for an address inside 15 minutes set `locked_until` 15 minutes ahead; a locked
key refuses even the right password with 429 `too_many_attempts` and a `Retry-After` header. Unknown
emails are counted like known ones. A success clears the email's counter; old failures age out of
the window. Rows are updated under `SELECT ... FOR UPDATE`, so concurrent attempts cannot undercount
and every API instance sees the same counts.

