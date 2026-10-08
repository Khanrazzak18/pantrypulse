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
