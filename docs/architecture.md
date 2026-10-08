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
