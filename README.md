# PantryPulse

AI food allocation for Harvest Bridge Food Bank, a hypothetical regional non-profit. See
`docs/spec-5.2.md` for the use case, `CLAUDE.md` for the build contract and `docs/architecture.md`
for design decisions.

**Status:** Stage 1 of 9 (scaffold). The full README (features, AI evaluation results, known
limitations) is written in Stage 8.

## Requirements

Docker, Node 20+, Python 3.12+, make.

## Quick start

```bash
cp .env.example .env     # then fill in POSTGRES_PASSWORD and JWT_SECRET
make setup               # backend/.venv + frontend dependencies
make db                  # Postgres 16 in Docker (creates pantrypulse and pantrypulse_test)
make dev                 # API on :8000, web on :3000 (Ctrl-C stops both)
```

Check it works: `curl localhost:3000/api/health` returns `{"status":"ok","database":"ok"}`.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | Install backend and frontend dependencies |
| `make db` | Start Postgres in Docker |
| `make migrate` | Alembic migrations (Stage 2) |
| `make seed` | Synthetic data and demo users (Stage 2) |
| `make dev` | API and web together |
| `make test` | ruff + pytest, then frontend lint, typecheck and build (needs `make db`) |
| `make eval` | Intake eval and forecast backtest (Stages 4 and 5) |
| `make refresh` | Weekly retrain and allocation job (Stage 6) |

Ports are set only in `.env`. Secrets never go in git; AWS access uses the CLI profile in
`AWS_PROFILE`, not access keys.
