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
