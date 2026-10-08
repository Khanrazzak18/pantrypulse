# Ports and settings come from the root .env (copy .env.example first).
-include .env
export

BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv

.PHONY: setup db db-down migrate seed dev test eval refresh check-env api-types

check-env:
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' and fill it in."; exit 1; }

setup: check-env
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
		--host 127.0.0.1 --port $(API_PORT)) & \
	(cd $(FRONTEND) && exec node_modules/.bin/next dev --port $(WEB_PORT)) & \
	wait

test: check-env
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/pytest -q
	cd $(FRONTEND) && npm run lint && npm run typecheck && npm run build

eval:
	@echo "eval: not implemented yet (Stage 4: intake eval, Stage 5: forecast backtest)"

refresh:
	@echo "refresh: not implemented yet (Stage 6: weekly retrain + allocation job)"
