# Ports and settings come from the root .env (copy .env.example first).
-include .env
export

BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv

.PHONY: setup db db-down migrate seed dev test security security-tools hooks e2e e2e-report eval backtest golden refresh check-env api-types simulate fairness aws-bootstrap aws-down

check-env:
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' and fill it in."; exit 1; }

setup: check-env hooks
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && npm install

db: check-env
	docker compose up -d --wait

db-down:
	docker compose down

migrate: check-env
	cd $(BACKEND) && .venv/bin/alembic upgrade head

seed: check-env
	cd $(BACKEND) && .venv/bin/python -m scripts.seed

# Regenerate the frontend's typed API client from the FastAPI OpenAPI document.
api-types: check-env
	cd $(BACKEND) && .venv/bin/python -m scripts.export_openapi
	cd $(FRONTEND) && npx openapi-typescript src/lib/api/openapi.json -o src/lib/api/schema.d.ts

# Runs API and web together; Ctrl-C stops both. `exec` makes each background job the
# server process itself, so the trap kills the servers and not just a wrapper shell.
dev: check-env
	@trap 'kill $$(jobs -p) 2>/dev/null' INT TERM EXIT; \
	(cd $(BACKEND) && exec .venv/bin/uvicorn app.main:create_app --factory --reload \
		--no-proxy-headers --host 127.0.0.1 --port $(API_PORT)) & \
	(cd $(FRONTEND) && exec node_modules/.bin/next dev --port $(WEB_PORT)) & \
	wait

test: check-env
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/pytest -q
	cd $(FRONTEND) && npm run lint && npm run typecheck && npm run build

# Security tools that are not Python or npm packages (gitleaks), installed into .tools/bin.
security-tools:
	tools/install-gitleaks.sh

# Turn on the pre-commit hook that blocks secrets and .env files.
hooks:
	git config core.hooksPath .githooks

# The whole security check: secrets (full git history and working tree), static analysis, dependency
# advisories, then the tests that prove access control, injection safety, rate limits and LLM safety.
SECURITY_TESTS := tests/test_authorization_matrix.py tests/test_api_fuzz.py tests/test_token_revocation.py \
	tests/test_security_headers.py tests/test_csrf_origin.py tests/test_rate_limits.py \
	tests/test_llm_safety.py tests/test_sql_hygiene.py tests/test_log_hygiene.py \
	tests/test_data_handling.py tests/test_precommit_hook.py tests/test_audit_gate.py \
	tests/test_body_stream_limit.py tests/test_trusted_proxies.py tests/test_raw_output_retention.py tests/test_iam_policy.py tests/test_security_checklist.py
security: check-env security-tools
	.tools/bin/gitleaks git --config .gitleaks.toml --redact --no-banner .
	.tools/bin/gitleaks dir --config .gitleaks.toml --redact --no-banner .
	cd $(BACKEND) && .venv/bin/bandit -r app scripts -c pyproject.toml -q
	cd $(BACKEND) && .venv/bin/pip-audit
	cd $(BACKEND) && .venv/bin/python -m scripts.npm_audit_gate
	cd $(BACKEND) && .venv/bin/pytest $(SECURITY_TESTS) -q

# End-to-end tests (Playwright). A separate API (port 8101) and web server (port 3101) run on the TEST
# database with a mock AI, so the dev app and real Bedrock are untouched. Uses the same database as
# `make test`: never run the two at the same time.
E2E_API_PORT := 8101
E2E_WEB_PORT := 3101
e2e: check-env
	cd $(BACKEND) && .venv/bin/python -m scripts.e2e_setup
	cd $(FRONTEND) && API_PORT=$(E2E_API_PORT) E2E_DIST_DIR=.next-e2e npx next build
	cd $(FRONTEND) && E2E_API_PORT=$(E2E_API_PORT) E2E_WEB_PORT=$(E2E_WEB_PORT) npx playwright test; \
		status=$$?; cd ../$(BACKEND) && .venv/bin/python -m scripts.testing_report; exit $$status

# Rewrite docs/testing/checklist.md and a11y-report.md from the last e2e run.
e2e-report: check-env
	cd $(BACKEND) && .venv/bin/python -m scripts.testing_report

# Rolling-origin forecast backtest on the seeded data (no AWS): saves a backtest run and writes
# docs/eval/forecast-backtest.md. Takes about a minute.
backtest: check-env
	cd $(BACKEND) && .venv/bin/python -m eval.forecast_backtest

# Replays the last 12 weeks under a manual rule and the optimizer: docs/eval/allocation-sim.md.
simulate: check-env
	cd $(BACKEND) && .venv/bin/python -m eval.allocation_sim

# Share of P50 demand met by county, distance band and pantry size, before and after the tiered-coverage
# objective, on the latest run, the 12-week simulation and a half-stock stress test: docs/eval/fairness.md.
# No AWS and no database writes; needs `make backtest` first.
fairness: check-env
	cd $(BACKEND) && .venv/bin/python -m eval.fairness

# Both evals. The intake eval calls Bedrock (costs tokens): docs/eval/intake-eval.md.
eval: check-env
	cd $(BACKEND) && .venv/bin/python -m eval.run_intake_eval
	cd $(BACKEND) && .venv/bin/python -m eval.forecast_backtest

# Rebuild the 50 golden manifests from their fixed seed (the committed files already match).
golden:
	cd $(BACKEND) && .venv/bin/python -m eval.make_golden_set

# Calls POST /api/admin/jobs/weekly-refresh (needs `make dev` running): forecast, then allocation.
refresh: check-env
	cd $(BACKEND) && .venv/bin/python -m scripts.refresh

# --- AWS deployment (see README, Deployment). Uses the AWS CLI profile `default` unless AWS_PROFILE is set.
aws-bootstrap:
	deploy/aws-bootstrap.sh

aws-down:
	deploy/aws-down.sh
