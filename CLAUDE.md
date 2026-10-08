# PantryPulse: Project Guide for Claude Code

PantryPulse is an AI food-allocation web app for Harvest Bridge Food Bank, a hypothetical regional non-profit that serves 85 partner pantries across six counties (about 40,000 households a month). This is Assignment 5.3 (AIML-515): a full-stack app that must run locally. The full use case is in `docs/spec-5.2.md`; this file is the build contract. Read both before writing code.

## The problem we are solving

- About 12% of perishable donations spoil before they reach a pantry.
- 1 in 4 pantries runs out of protein or fresh produce before the end of each distribution week.
- Three coordinators spend about 12 hours a week re-typing donation manifests and deciding allocations by spreadsheet, phone and memory.
- Nearly half of donations are perishable with 3 to 7 days of shelf life. Manifests arrive as emails, PDFs and photos of pallets.

## Users and roles

| Role | Who | Can do |
| --- | --- | --- |
| `coordinator` | Warehouse coordinators | Upload donations, review AI extraction, run forecasts and allocations, approve/edit/reject allocations |
| `pantry_manager` | One per pantry | See incoming deliveries for their pantry only, submit shortage reports |
| `admin` | Operations director | Everything a coordinator can do, plus the impact dashboard, monthly AI summary and the weekly refresh job |

## MVP features (build all five; nothing else)

1. **AI donation intake.** Upload a forwarded email (text/.eml), PDF or photo. Amazon Bedrock (Claude) returns structured JSON per line item: item name, category, quantity, unit, estimated weight in lbs, expiry date, storage type (ambient, refrigerated, frozen) and a 0 to 1 confidence per field. Validate with Pydantic. Highlight fields under 0.8 confidence. The coordinator edits and confirms before anything enters inventory.
2. **Demand forecasting.** Weekly forecast per pantry and category with a P10 to P90 prediction interval. One LightGBM global model compared against a seasonal-naive baseline (same week last year). Features: lagged demand, rolling means, week of year, school-holiday flag, benefit-issuance week, weather (temperature, precipitation), pantry and category IDs. Correct for censored demand: past distributions were capped by supply, so weeks with a shortage report get an uplift based on the shortage severity and household visit counts.
3. **Expiry-aware allocation.** An OR-Tools linear program assigns inventory lots to pantries to maximize forecast demand met, while penalizing expiry risk (soonest-expiring stock goes first) and travel distance, within each pantry's cold and dry storage capacity. Bedrock writes a one-line plain-English reason per recommendation, for example "Pantry 14: forecast short 300 lb dairy, 6 miles away." Batch all reasons into one LLM call and fall back to a template reason if the call fails. Coordinators approve, edit or reject each one; every edit is logged with old value, new value, user and time.
4. **Pantry portal.** Mobile-first view of incoming deliveries for the logged-in pantry manager, plus a shortage report form that takes under 30 seconds and feeds the next forecast.
5. **Impact dashboard.** Spoilage % (expired lbs / received perishable lbs), stockouts (shortage reports), pounds distributed and households served, over time and by category, with Recharts. Includes an AI-drafted monthly summary for grant reports, generated from aggregated numbers only, editable and approved by an admin before it is saved as final.

Out of scope: the "Ask PantryPulse" assistant (Phase 2 in the spec). Do not build it.

## Local stack (production equivalents in brackets)

| Layer | Local build | Production later |
| --- | --- | --- |
| Frontend | Next.js (App Router, TypeScript strict), Tailwind CSS, Recharts | Same, App Runner |
| API | FastAPI, Python 3.12+ in a virtual environment at `backend/.venv` (never the conda base environment), Pydantic v2 | Same, App Runner |
| Database | PostgreSQL 16 in Docker Compose, SQLAlchemy 2.x, Alembic | Amazon RDS |
| Generative AI | Amazon Bedrock Converse API via boto3, model from `BEDROCK_MODEL_ID` | Same, IAM role |
| Forecasting | LightGBM, pandas | Same |
| Optimization | Google OR-Tools (GLOP linear solver) | Same |
| Auth | JWT in an httpOnly cookie, bcrypt/argon2 password hashes, 3 roles | Amazon Cognito groups |
| File storage | `StorageBackend` interface with `LocalStorage` (folder `backend/var/uploads`) | `S3Storage` |
| Scheduled job | `POST /api/admin/jobs/weekly-refresh` + `make refresh` | EventBridge Scheduler + Lambda |

Ports are defined once in `.env` and nowhere else: web 3000, API 8000, Postgres 5433 on the host (avoids clashing with a local Postgres on 5432).

The browser talks to one origin: Next.js rewrites `/api/*` to the FastAPI server, so no CORS setup and the auth cookie just works.

## Folder structure

```
pantrypulse/
├── CLAUDE.md
├── README.md
├── Makefile                 # setup, db, migrate, seed, dev, test, eval, refresh
├── docker-compose.yml       # postgres (+ test database)
├── .env.example             # every variable, no real values
├── .gitignore
├── docs/
│   ├── spec-5.2.md          # the use case, pasted verbatim
│   ├── dev-log.md           # one entry per stage (see "Dev log" below)
│   ├── architecture.md
│   └── eval/                # intake-eval.md, forecast-backtest.md, allocation-sim.md
├── backend/
│   ├── pyproject.toml
│   ├── alembic/ , alembic.ini
│   ├── app/
│   │   ├── main.py, config.py, db.py, logging.py, errors.py
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── api/             # one router per area: auth, donations, donors, pantries, forecasts, allocations, pantry_portal, dashboard, admin, health
│   │   ├── services/        # intake, forecasting, forecast_runs, optimizer, allocation_runs, allocation_reasons, dashboard, summaries, number_check
│   │   ├── ai/              # llm_provider.py (Bedrock), prompts/
│   │   ├── auth/            # jwt, password hashing, role dependencies, login lockout (throttle)
│   │   ├── storage/         # StorageBackend, LocalStorage, S3Storage stub
│   │   └── jobs/            # weekly_refresh.py
│   ├── scripts/             # generate_synthetic_data.py, seed.py, refresh.py, export_openapi.py
│   ├── eval/                # golden/ manifests + expected.json (+ KEY.sha256), run_intake_eval.py, forecast_backtest.py, allocation_sim.py
│   └── tests/
└── frontend/
    ├── package.json
    └── src/
        ├── app/             # login, coordinator (pantries, donations, forecasts, allocations), pantry, admin/dashboard
        ├── components/
        └── lib/api/         # client generated from FastAPI's OpenAPI schema (openapi-typescript)
```

## Data model (minimum)

`users`, `pantries` (name, county, lat/lon, cold and dry capacity in lbs, baseline households), `categories` (8 fixed: produce, dairy, protein, bakery, frozen, canned, dry_goods, beverages; perishable flag), `donors`, `donations` (source type, file key, status pending_review/confirmed/rejected, raw LLM output as JSONB, model id, latency ms), `donation_items` (fields above + per-field confidence JSONB + edited flag), `inventory_lots`, `distributions` (pantry, category, week, lbs, households), `shortage_reports`, `forecast_runs` (model, WAPE for LightGBM and baseline, train window), `forecasts` (P10/P50/P90), `allocation_runs`, `allocations` (lot, pantry, lbs, reason, status, final lbs, decided by/at, delivery date), `allocation_edits`, `monthly_summaries`. Use foreign keys, NOT NULL and CHECK constraints (quantities > 0, valid enums).

## Synthetic data

`scripts/generate_synthetic_data.py` with a fixed random seed: 85 pantries across 6 counties, 8 categories, 3 years of weekly distributions with seasonality, school holidays, benefit-issuance cycles and weather effects; shortage reports for about 1 in 4 pantries per week; perishable spoilage near 12% in the baseline period. It must be reproducible: same seed, same numbers.

## AI quality gates

- **Intake eval:** `backend/eval/golden/` holds 50 synthetic manifests (30 email text, 15 PDF, 5 photo-style images) each with `expected.json`. `make eval` computes field-level accuracy and writes `docs/eval/intake-eval.md`. Target: at least 95%.
- **Forecast backtest:** rolling-origin backtest over the last 12 weeks, WAPE per pantry and category, LightGBM vs seasonal-naive. Write `docs/eval/forecast-backtest.md`. Target: WAPE under 20%. Features must only use information available at forecast time; list every leakage check in the report.

## Rules (lessons from App #1, ClauseCompass AI)

These come from problems App #1 only hit at deployment. Follow them from the first commit.

1. **Plan before code.** For each stage, state the plan and the files you will touch, then wait for approval.
2. **Small, scoped tasks.** One stage per prompt. Stop at the end of each stage and report.
3. **Tests first.** Write the pytest tests for a feature before its code. A stage is not done until `make test` passes.
4. **Stateless API.** No in-memory caches of database data (App #1 had a stale-read bug across instances). Any cache must be keyed by a version stored in the database.
5. **Storage behind an interface.** Never write app data to local disk directly; go through `StorageBackend` (App #1 had to be refactored from a JSON file to S3).
6. **A real database with constraints.** No JSON-file stores, no last-write-wins (App #1's known limitation).
7. **Secrets.** Nothing secret in code, git, logs or chat. `.env` is gitignored before the first commit; `.env.example` lists every variable. AWS access comes from the AWS CLI profile in `AWS_PROFILE`, never access keys in `.env`. If a secret ever appears in the conversation, stop and tell me.
8. **Logging and health from day one.** Structured JSON logs with request id, route, status and duration; LLM calls also log model, latency and token counts. `GET /api/health` checks the database.
9. **LLM output is untrusted data.** Validate every response against a Pydantic schema; retry once with backoff on timeouts or invalid JSON; then return a clear error the UI can show. Never let LLM output write to the database without coordinator confirmation.
10. **Human in the loop.** Coordinators approve every allocation; admins approve every monthly summary.
11. **One error envelope.** API errors return `{"error": {"code", "message", "details"}}` with the right HTTP status. The frontend shows loading states, empty states and readable errors on every page.
12. **Validate every form** on the client (inline messages) and the server (Pydantic). Uploads: pdf, png, jpg, webp, txt, eml only, 10 MB max.
13. **Mobile-first** for the pantry portal; every page must work at 375 px wide.
14. **Commit after every stage** with a message starting `Stage N:` so git timestamps record the build timeline.

## Dev log

At the end of every stage, append to `docs/dev-log.md`:

```
## Stage N: <name>  (<start time> to <end time>)
- Built: <what>
- Tests: <command and result>
- Problems found and fixed: <what went wrong, root cause, fix>
- Decisions: <any choice you made that the spec did not specify>
```

## Commands (keep the README in sync)

```
make setup     # install backend and frontend dependencies
make db        # start Postgres in Docker
make migrate   # alembic upgrade head
make seed      # synthetic data + demo users
make dev       # API on :8000 and web on :3000
make test      # pytest + frontend lint, typecheck and build
make eval      # intake golden-set eval + forecast backtest
make refresh   # run the weekly retrain + allocation job
```

Demo logins (local only, printed by `make seed` and listed in the README): one coordinator, one admin, one pantry manager.

## Definition of done (whole project)

- `make setup && make db && make migrate && make seed && make dev` works on a fresh clone with only `.env` filled in.
- `make test` passes with zero failures; frontend lint, typecheck and production build pass.
- No errors in the browser console or API logs while walking through all five features.
- `make eval` meets both targets, or the report states the actual numbers honestly.
- README covers: problem, features, architecture, setup, environment variables, demo logins, commands, testing, AI evaluation results, known limitations.

## Troubleshooting notes

- This Mac uses conda (the prompt shows `(base)`). Create and use `backend/.venv` with `python3 -m venv`; run `conda deactivate` first if packages install into conda by mistake.
- LightGBM import error on macOS: `brew install libomp`.
- Bedrock `AccessDeniedException` on an Anthropic model: submit the one-time Anthropic use-case form by opening the model in the Bedrock console playground, then retry.
- Bedrock says on-demand throughput is not supported for a model: use its cross-region inference profile ID (starts with `us.`) as `BEDROCK_MODEL_ID`.
- Port already in use: change it in `.env` only.
