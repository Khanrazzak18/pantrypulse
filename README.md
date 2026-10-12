# PantryPulse

AI food allocation for **Harvest Bridge Food Bank**, a hypothetical regional non-profit with 85
partner pantries in six counties. Built as Assignment 5.3 (AIML-515). The use case is in
[docs/spec-5.2.md](docs/spec-5.2.md), the build rules in [CLAUDE.md](CLAUDE.md), design decisions in
[docs/architecture.md](docs/architecture.md) and the build history in [docs/dev-log.md](docs/dev-log.md).

## The problem

About 12% of perishable donations spoil before they reach a pantry, 1 in 4 pantries runs out of
protein or fresh produce before the end of each week, and three coordinators spend about 12 hours a
week re-typing donation manifests and deciding who gets what from spreadsheets and memory.
PantryPulse reads manifests with an AI model, forecasts each pantry's demand, proposes an
expiry-aware allocation, and leaves every decision to a person.

## Features

| # | Feature | Who | Where |
| --- | --- | --- | --- |
| 1 | **AI donation intake.** Upload an email, PDF or photo; Amazon Bedrock extracts items, quantities and expiry dates; a coordinator edits (low-confidence fields highlighted) and confirms before anything becomes inventory. | Coordinator, admin | Donations |
| 2 | **Demand forecast.** Weekly P10/P50/P90 per pantry and category (LightGBM, compared with a same-week-last-year baseline), corrected for demand hidden by past shortages. | Coordinator, admin | Forecasts |
| 3 | **Expiry-aware allocation.** An OR-Tools linear program assigns lots to pantries (soonest-expiring first, within storage capacity); reasons in plain English; approve, edit or reject each row, every edit logged. | Coordinator, admin | Allocations |
| 4 | **Pantry portal.** Mobile-first list of incoming deliveries and a 30-second shortage report that feeds the next forecast. | Pantry manager | My pantry |
| 5 | **Impact dashboard.** Spoilage, stockouts, pounds distributed, households served, a date filter, an AI-drafted monthly grant summary that an admin edits and approves, and the weekly refresh. | Admin | Dashboard |

Out of scope: the Phase 2 "Ask PantryPulse" assistant.

## Architecture

```
Browser ──> Next.js (:3000) ──/api/* proxy──> FastAPI (:8000) ──> PostgreSQL 16 (:5433)
                                                   │
                                                   ├──> Amazon Bedrock (Claude): intake, allocation reasons, monthly summary
                                                   └──> StorageBackend (LocalStorage now, S3 later): uploaded manifests, model files
```

| Layer | Local build |
| --- | --- |
| Frontend | Next.js (App Router, TypeScript strict), Tailwind CSS, Recharts, a typed client generated from the API's OpenAPI schema |
| API | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic; one error envelope `{"error": {"code", "message", "details"}}` |
| Database | PostgreSQL 16 in Docker, with foreign keys and CHECK constraints |
| AI | Amazon Bedrock Converse API (forced tool use, validated output, one retry on bad JSON or timeouts) |
| Forecasting and optimization | LightGBM, pandas, Google OR-Tools (GLOP) |
| Auth | JWT in an httpOnly cookie, argon2 hashes, three roles, database-backed login lockout |

The API keeps no state in memory (every counter and cache lives in the database), writes files only
through `StorageBackend`, and treats model output as untrusted: nothing a model writes reaches the
database without a person confirming it.

```
pantrypulse/
├── CLAUDE.md  README.md  Makefile  docker-compose.yml  .env.example
├── docs/            spec, architecture, dev-log, eval/ (intake, forecast backtest, allocation simulation)
├── backend/
│   ├── app/         api/ (one router per area), models/, schemas/, services/, ai/, auth/, storage/, jobs/
│   ├── alembic/     migrations
│   ├── scripts/     synthetic data generator, seed, refresh, OpenAPI export
│   ├── eval/        golden manifests and the three evaluations
│   └── tests/
└── frontend/src/    app/ (pages), components/, lib/ (helpers and the generated API client)
```

## Setup from a fresh clone

Requirements: Docker, Node 20+, Python 3.12+, make. AWS access to Amazon Bedrock is needed only for
the AI features (intake, allocation reasons, monthly summary, `make eval`); everything else runs
without it, and allocation falls back to template reasons.

```bash
cp .env.example .env     # then set POSTGRES_PASSWORD and JWT_SECRET (see below); leave the rest
make setup               # backend/.venv and frontend dependencies
make db                  # Postgres 16 in Docker (creates the app and test databases)
make migrate             # create the tables
make seed                # three years of synthetic history, current stock, demo users
make backtest            # forecast backtest (about a minute); the Forecasts page reads it
make dev                 # API on :8000, web on :3000 (Ctrl-C stops both)
```

Then open http://localhost:3000, log in (see Demo logins), open **Forecasts** and click **Run
forecast**, then **Allocations** and click **Run allocation**. `curl localhost:3000/api/health`
returns `{"status":"ok","database":"ok"}` when the stack is up.

Generate the JWT secret with `openssl rand -hex 32`. To use AI features:

1. Credentials come from an AWS CLI profile, never from `.env` keys:
   `aws configure --profile pantrypulse`, then keep `AWS_PROFILE=pantrypulse` and
   `AWS_REGION=us-east-1` in `.env`.
2. `BEDROCK_MODEL_ID` must be an inference profile ID (it starts with `us.`). The default is
   `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
3. The first time an account uses an Anthropic model, open it once in the Bedrock console
   playground and submit the one-time use-case form.
4. Give the AWS user permission to call the model, and nothing else. **Minimum IAM policy**
   (also in `docs/security/iam-policy.json`; replace `<ACCOUNT_ID>`). `bedrock:InvokeModel` is the
   permission the Converse API checks. A `us.` inference profile can route to several US regions, so
   the foundation-model ARN uses `us-*` for the region. There are no discovery actions: the app never
   lists or describes models, and the policy denies listing them.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeClaudeHaiku45ForPantryPulse",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:us-*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
      ]
    }
  ]
}
```

Switching models means changing both the model ID in `.env` and the resources above.
`AmazonBedrockFullAccess` and `AmazonBedrockReadOnly` also work but grant far more than the app needs.

Tests never call Bedrock (they use a scripted fake and a guard fails any test that tries to create
an AWS client). Only the running app and `make eval` use the real service. The local file store
needs no AWS permissions; a production S3 store would additionally need `s3:GetObject`,
`s3:PutObject` and `s3:DeleteObject` on one bucket.

## Environment variables

All live in `.env` (see `.env.example`, which has a comment for each). Ports are defined only there.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `WEB_PORT` | yes | 3000 | Port of the web app |
| `API_PORT` | yes | 8000 | Port of the API (the web app proxies `/api/*` to it) |
| `POSTGRES_PORT` | yes | 5433 | Host port of Postgres |
| `POSTGRES_USER` | yes | pantrypulse | Database user |
| `POSTGRES_PASSWORD` | yes | none | Database password |
| `POSTGRES_HOST` | no | localhost | Database host |
| `POSTGRES_DB` | yes | pantrypulse | The app database |
| `POSTGRES_TEST_DB` | yes | pantrypulse_test | The database `make test` empties and refills |
| `JWT_SECRET` | yes | none | Signs login cookies; at least 32 characters |
| `SESSION_HOURS` | no | 8 | How long a login lasts |
| `COOKIE_SECURE` | no | false | Mark the cookie Secure (set true over https) |
| `DEMO_COORDINATOR_PASSWORD`, `DEMO_ADMIN_PASSWORD`, `DEMO_PANTRY_MANAGER_PASSWORD` | for `make seed` | demo values | Passwords of the demo users |
| `AWS_PROFILE` | for AI features | pantrypulse | AWS CLI profile used for Bedrock |
| `AWS_REGION` | for AI features | us-east-1 | Bedrock region |
| `BEDROCK_MODEL_ID` | for AI features | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Model or inference profile |
| `STORAGE_DIR` | no | backend/var/uploads | Where uploads are kept (relative to the repo root) |
| `LOG_LEVEL` | no | INFO | Log verbosity |
| `ALLOWED_ORIGINS` | no | derived from `WEB_PORT` | Comma-separated origins allowed to send state-changing requests (the Origin check) |
| `EXPOSE_API_DOCS` | no | false | Serve `/api/docs` and the OpenAPI JSON (leave off outside local development) |
| `TRUSTED_PROXIES` | no | empty (`.env.example`: `127.0.0.1,::1`) | Proxies whose `X-Forwarded-For` is believed; production must list the real proxy and run uvicorn with `--no-proxy-headers` |
| `RAW_OUTPUT_RETENTION_DAYS` | no | 90 | Days after review before the raw model output is cleared (weekly refresh) |
| `RATE_LIMIT_UPLOADS_PER_HOUR` | no | 20 | Donation uploads per user per hour |
| `RATE_LIMIT_AI_PER_HOUR` | no | 30 | Calls per user per hour to each AI endpoint (forecast, allocation run, reasons, summary draft) |
| `RATE_LIMIT_REFRESH_PER_HOUR` | no | 6 | Weekly refresh runs per user per hour |

## Demo logins (local only)

`make seed` creates these users. The passwords are the `DEMO_*` values in `.env`; the defaults from
`.env.example` are below. They are demo credentials for local development, not real secrets.
Log in at http://localhost:3000/login. Five wrong passwords for one email lock it for 15 minutes.

| Role | Email | Password variable | Default |
| --- | --- | --- | --- |
| Coordinator | `coordinator@harvestbridge.example.org` | `DEMO_COORDINATOR_PASSWORD` | `demo-coordinator-pw` |
| Admin | `admin@harvestbridge.example.org` | `DEMO_ADMIN_PASSWORD` | `demo-admin-pw` |
| Pantry manager (Pantry 14) | `manager14@harvestbridge.example.org` | `DEMO_PANTRY_MANAGER_PASSWORD` | `demo-manager-pw` |

An admin can do everything a coordinator can, plus the dashboard, the monthly summary and the weekly
refresh. A pantry manager sees only their own pantry.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | Install backend and frontend dependencies |
| `make db` / `make db-down` | Start or stop Postgres in Docker |
| `make migrate` | Apply Alembic migrations to the app database |
| `make seed` | Reload the synthetic history, current stock and demo users (destroys the app database's contents) |
| `make dev` | API and web together |
| `make api-types` | Regenerate the frontend's typed API client after changing the API |
| `make test` | ruff and pytest, then frontend lint, typecheck and production build (needs `make db`) |
| `make backtest` | Forecast backtest over the last 12 weeks (no AWS, about a minute); writes `docs/eval/forecast-backtest.md` |
| `make simulate` | Replay the last 12 weeks under a manual rule and the optimizer (run `make backtest` first); writes `docs/eval/allocation-sim.md` |
| `make e2e` | End-to-end tests (Playwright) on a separate API (port 8101) and web server (port 3101) using the test database and a mock AI; writes `docs/testing/checklist.md` and `a11y-report.md`. Never run it at the same time as `make test` |
| `make fairness` | Share of demand met by county, distance band and pantry size, before and after the fairness change, including a half-stock stress test (run `make backtest` first; no AWS); writes `docs/eval/fairness.md` |
| `make security` | gitleaks (history and tree), bandit, pip-audit, an npm audit gate and the security tests |
| `make e2e-report` | Rewrite the two testing reports from the last e2e run |
| `make eval` | The intake eval (calls Bedrock, costs about 245,000 tokens) and then the backtest |
| `make golden` | Rebuild the golden manifests from their fixed seed |
| `make refresh` | Weekly job over HTTP (needs `make dev`): trains the forward forecast, then reruns allocation, about 14 s |

## Testing

`make test` runs ruff and the backend suite (1,176 tests against the separate test database), then
frontend lint, typecheck and the production build. It never calls AWS. Tests are written before the
code they check; the suites cover constraints and migrations, auth and lockout, intake, forecasting
and its leakage checks, the optimizer, allocation workflow, the pantry portal, dashboard numbers,
summaries, error envelopes and input validation.

### End-to-end tests and the testing checklist

The whole testing story (approach, final counts, every bug, the security measures, accessibility and fairness) is in [docs/testing/report.md](docs/testing/report.md); the tick-list of security measures, each with the test that proves it, is [docs/security/checklist.md](docs/security/checklist.md).

`make e2e` drives the real pages with Playwright at 375, 768 and 1280 px in Chromium and 1280 px in
WebKit (Safari's engine), signed in as each role. It starts its own API on port 8101 (the real app,
wired to the test database, a scripted mock AI, a throwaway upload folder and a pinned date) and its
own production web server on port 3101, so your dev app and real Bedrock are never touched. The mock
AI and the reset route live only in `backend/scripts/e2e_server.py`; a test proves the normal app
cannot load them. Every feature, button and error state is listed in
[docs/testing/checklist.md](docs/testing/checklist.md) with the test that covers it, accessibility
scan results are in [docs/testing/a11y-report.md](docs/testing/a11y-report.md) (any WCAG 2.1 A or AA violation
fails the run), what was built for keyboard, screen-reader, zoom and reduced-motion users is in
[docs/accessibility.md](docs/accessibility.md), and bugs found but not
yet fixed are in [docs/testing/bugs.md](docs/testing/bugs.md). A test marked `test.fail()` with a
`[BUG-n]` in its title proves a known bug and flips to a failure the moment the bug is fixed.
`make test` and `make e2e` share the test database, so run them one after the other.

## Error handling

- **One error envelope** for every API error: `{"error": {"code", "message", "details", "request_id"}}`. The
  request id is also the `X-Request-ID` header and is in every log line, so a message a user quotes leads
  straight to the full detail in the logs. Stack traces never reach a client.
- **Outages are 503, not 500.** If the database cannot be reached, every route answers `503
  service_unavailable` with `Retry-After`, and `/api/health` answers 503 with `details: {"database": "down"}`.
  The web app shows "PantryPulse is temporarily unavailable" with a Try again button (and never treats an
  outage as a logout); buttons show the same message.
- **Input is checked once, at the API boundary,** with shared types in `backend/app/schemas/types.py`: ids
  must fit the database (out of range is a 404), dates must be 2020 to 2100, months 2020-01 to 2100-12, and
  text may not contain control characters. Text the AI writes is cleaned the same way. The forms check the
  same rules inline.
- **Browser:** every API call has a time limit (30 s, 120 s for uploads and AI calls), the app shows a banner
  when the browser is offline, and an unhandled promise rejection shows a dismissible banner instead of failing
  silently. Every route segment has an error and a not-found screen, plus a global one.
- **Fuzz test:** `backend/tests/test_api_fuzz.py` sends hostile ids, dates, numbers, very long text and
  control characters to every API route as a logged-out caller, a pantry manager and an admin, and fails on
  any HTTP 500.

## Using the app, by role

- **Coordinator:** *Donations* (upload, review, confirm), *Forecasts* (Run forecast), *Allocations*
  (Run allocation, then approve, edit or reject; "Approve all shown" asks for confirmation).
- **Pantry manager:** *My pantry* shows approved deliveries and the shortage form. A second report
  for the same category and week updates the first.
- **Admin:** *Dashboard* (date filter, charts, monthly summary: draft with AI, edit, approve) and
  **Run weekly refresh**.

Every page shows loading, empty and error states, works from 375 px wide, and every API error uses
the same envelope.

## AI evaluation results

| Evaluation | Result | Report |
| --- | --- | --- |
| Intake extraction, 50 synthetic manifests | **99.5%** field accuracy (1,999 of 2,009; target 95%) on the Stage 8 prompt and a frozen answer key. Earlier: 92.9% on the first scoring, 98.7% after the key was corrected. | [intake-eval.md](docs/eval/intake-eval.md) |
| Forecast backtest, last 12 weeks | **WAPE 10.7%** vs 14.5% for the same-week-last-year baseline (target 20%); interval coverage 77.2% (aim 80%) | [forecast-backtest.md](docs/eval/forecast-backtest.md) |
| Allocation simulation | Stockouts **not conclusive**; spoilage **cannot be tested** on this data | [allocation-sim.md](docs/eval/allocation-sim.md) |

**Intake.** The 99.5% is not a blind result: the key was frozen and committed before the prompt was
changed (`make eval` refuses to run if it differs), but the prompt fixes cure mistakes seen on the
same synthetic set, so read it as "the known mistakes are fixed". Remaining mistakes are listed in
the report.

**Forecast.** The correction for censored demand made no measurable difference on this data (10.2%
against true demand with and without it), because only about 3% of weeks have a shortage report.
The report lists every leakage check and the test behind it.

**Allocation simulation: what it supports and what it cannot.**

`make simulate` replays the last 12 weeks of the synthetic data twice, once with a stand-in for
today's manual routine and once with the optimizer, and scores both against the true demand
(full report with the assumptions: [docs/eval/allocation-sim.md](docs/eval/allocation-sim.md)).

**This synthetic data can test the stockout target but cannot test the spoilage target.** The data
generator draws spoilage for each lot independently of how the food is allocated, so no allocation
decision can change the spoilage in the history, and the 12% baseline is a property of the
generator's settings. The simulation's spoilage figures only count food that expires in the
warehouse or is sent beyond need; they are not evidence for or against reducing spoilage from 12%
to under 8%.

To test spoilage for real, a pilot would need to measure, for a period before and a period during
the optimizer's use, lot-level pounds received, shipped, distributed and discarded by date, with
the cause of every discard (warehouse expiry, pantry expiry, damage); a comparison that controls for
what was donated (pilot against comparison pantries in the same weeks, or a stepped rollout); and
pantry reports of food that expired after delivery.

On stockouts the simulation is **not conclusive**. With two deliveries a week (the primary setup)
pantry-weeks with a shortage were 31.3% for the manual stand-in and 34.8% for the optimizer (it was
33.2% before Stage 13's fairness change, which spreads a shortage over more pantries instead of
concentrating it); the optimizer was better with one delivery a week (46.2% against 57.4%) and worse
than a coordinator who keeps track of what has already been sent (18.0%). The result depends on how good the manual process
is assumed to be, which nobody has measured, so the 30% stockout target is not shown by this data.

## Accessibility and responsible AI

- **Accessibility** targets WCAG 2.1 AA. A skip link, landmarks, a title per route, visible focus, linked form errors with focus on the
  first one, announcements, modal dialogs that trap focus and return it, captions and scopes on tables, a text summary and "View as table"
  for every chart, no meaning in colour alone, reduced motion, 200% zoom and keyboard-only journeys are built and tested; the axe scans
  must show zero violations. Details and what is not covered (no manual screen-reader test): [docs/accessibility.md](docs/accessibility.md).
- **Responsible AI** (human review, transparency, data minimisation, guardrails, accountability, limitations):
  [docs/responsible-ai.md](docs/responsible-ai.md). **Fairness:** allocation was measured for the share of forecast demand met by county,
  distance band and pantry size. With normal stock every group is within 1 point of the average; with half the stock the old objective gave
  the farthest pantries 1.4% of their forecast (59 points below average) and the tiered-coverage objective now gives them 56.9% (4 points below),
  at the cost of more pound-miles and more pantries being a little short instead of a few being starved ([docs/eval/fairness.md](docs/eval/fairness.md)).

## Security

`docs/security/audit.md` lists every finding (OWASP Top 10 and LLM Top 10, severity, evidence, fix,
test) and `docs/security/checklist.md` is the pre-deploy checklist. `make security` runs gitleaks
(history and working tree), bandit, pip-audit, an npm audit gate, the role-by-route test and the
fuzz test. A pre-commit hook (installed by `make setup`) blocks secrets and `.env` files.

- Logout and deactivation revoke every session of that user (`token_version`).
- State-changing requests must be same-origin; responses carry CSP (nonce, no `'unsafe-inline'` for
  scripts), frame-ancestors, nosniff, Referrer-Policy and Permissions-Policy, plus HSTS when
  `COOKIE_SECURE=true`. Styles still need `'unsafe-inline'` because Next.js and Recharts write
  inline style attributes.
- Uploads, AI endpoints and the weekly refresh are rate limited per user in the database. Request
  bodies are counted as they stream in (413 at the limit, chunked or not). `X-Forwarded-For` is
  trusted only from `TRUSTED_PROXIES`. Raw model output is cleared 90 days after review.
- One accepted npm risk: a dev-only advisory (braces, via eslint-config-next) with no patched
  release; production dependencies audit clean.

## Known limitations

- **Login lockout counts one address per proxy hop.** Five failures for one email, or 20 from one
  address, in 15 minutes lock that email or address for 15 minutes (counted in the database).
  `X-Forwarded-For` is believed only from proxies in `TRUSTED_PROXIES`; behind a shared office or
  carrier address, many real users can share one address.
- **AI work runs inside the request.** A manifest takes 5 to 30 seconds (worst case about 95 with a
  retry); there is no background queue. Request size is enforced while the body streams in, but a
  production proxy should still enforce its own limit and timeouts.
- **The model makes mistakes the checks cannot see.** Intake leaves a few wrong dates and weights
  (highlighted when it was unsure); allocation reasons and monthly summaries are checked for invented
  numbers but not for a wrong label on a real number (a first summary draft called pounds "items").
  That is why a person approves every allocation and every summary.
- **Forecast limits.** One week ahead only; last week's weather rather than the forecast week's (no
  weather forecast exists in the data); only reported shortages are corrected and the correction
  constants are assumptions; intervals are slightly narrow (77.2% coverage).
- **Allocation limits.** The optimizer never sends more than a pantry's P90 forecast, so a week when
  demand exceeds P90 leaves that pantry short even with stock in hand (62% of its simulated
  shortages). Pantry capacity is a weekly intake limit, not live storage, and distance is
  straight-line from one warehouse.
- **The simulation does not establish the 12% to 8% spoilage target or the 30% stockout target.**
- **Nothing runs the weekly refresh on a schedule.** Production would use EventBridge calling the
  same endpoint; `make refresh` logs in as the demo admin.
- **Deliveries are planned dates, not confirmed receipts**, and rejected uploads are kept as an audit
  record.
- **All data is synthetic.** Harvest Bridge and its six counties are fictional, and the weather,
  school holidays and benefit weeks are generated from a fixed seed.
