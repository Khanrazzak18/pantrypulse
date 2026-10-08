# PantryPulse

AI food allocation for Harvest Bridge Food Bank, a hypothetical regional non-profit. See
`docs/spec-5.2.md` for the use case, `CLAUDE.md` for the build contract and `docs/architecture.md`
for design decisions.

**Status:** Stage 2 of 9 (database, data models and synthetic data). The full README (features, AI evaluation results, known
limitations) is written in Stage 8.

## Requirements

Docker, Node 20+, Python 3.12+, make.

## Quick start

```bash
cp .env.example .env     # then fill in POSTGRES_PASSWORD and JWT_SECRET (the DEMO_* lines can stay as they are)
make setup               # backend/.venv + frontend dependencies
make db                  # Postgres 16 in Docker (creates pantrypulse and pantrypulse_test)
make migrate             # create the tables
make seed                # synthetic history + demo users
make dev                 # API on :8000, web on :3000 (Ctrl-C stops both)
```

Check it works: `curl localhost:3000/api/health` returns `{"status":"ok","database":"ok"}`.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | Install backend and frontend dependencies |
| `make db` | Start Postgres in Docker |
| `make migrate` | Apply Alembic migrations to the app database |
| `make seed` | Reload the synthetic history and demo users (destructive for the app database) |
| `make dev` | API and web together |
| `make test` | ruff + pytest, then frontend lint, typecheck and build (needs `make db`) |
| `make eval` | Intake eval and forecast backtest (Stages 4 and 5) |
| `make refresh` | Weekly retrain and allocation job (Stage 6) |

Ports are set only in `.env`. Secrets never go in git; AWS access uses the CLI profile in
`AWS_PROFILE`, not access keys.

## Demo logins (local only)

`make seed` creates these users. The passwords are the `DEMO_*` values in `.env`; the defaults in
`.env.example` are below. They are demo credentials for local development, not real secrets.
Login itself arrives in Stage 3.

| Role | Email | Password variable | Default |
| --- | --- | --- | --- |
| Coordinator | `coordinator@harvestbridge.example.org` | `DEMO_COORDINATOR_PASSWORD` | `demo-coordinator-pw` |
| Admin | `admin@harvestbridge.example.org` | `DEMO_ADMIN_PASSWORD` | `demo-admin-pw` |
| Pantry manager (Pantry 14) | `manager14@harvestbridge.example.org` | `DEMO_PANTRY_MANAGER_PASSWORD` | `demo-manager-pw` |

`make seed` fails with a clear message if any of these variables is missing from `.env`.

## About the data

All data is synthetic. Harvest Bridge Food Bank is hypothetical, the six counties are fictional,
and **the weather, school holidays and benefit-payment weeks are generated, not real**. The
generator uses a fixed seed, so the same data comes out every time. See
`docs/architecture.md` for how it works and the baseline it produces.
