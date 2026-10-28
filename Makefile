# Single entry point for dev tasks (see AGENTS.md §4).
SHELL := /bin/bash

# Test databases come from `docker compose --profile test` (ports 55432 / 56379).
# Override to use your own, e.g. `make test TEST_DATABASE_URL=postgresql+asyncpg://...`.
# Set TEST_DB_EXTERNAL=1 to skip starting the compose test containers.
TEST_DATABASE_URL ?= postgresql+asyncpg://postgres:test@localhost:55432/mallt_test
TEST_REDIS_URL ?= redis://localhost:56379/15
export TEST_DATABASE_URL TEST_REDIS_URL

# The print agent is standalone (one runtime dependency); dev tools come in through uv, no project install.
AGENT_RUN = uv run --no-project --with websockets --with pytest --with pytest-asyncio --with ruff

.PHONY: dev dev-redis down test test-up lint fmt migrate migration api-client seed-admin e2e

dev: ## nginx + web + api against Neon; Redis not required
	docker compose up --build

dev-redis: ## same, plus Redis and the ARQ worker
	COMPOSE_REDIS_URL=redis://redis:6379/0 docker compose --profile redis up --build

down:
	docker compose --profile redis --profile test down

test-up:
ifndef TEST_DB_EXTERNAL
	docker compose --profile test up -d --wait postgres-test redis-test
endif

test: test-up
	cd backend && uv run pytest
	cd frontend && pnpm test
	cd print-agent && $(AGENT_RUN) python -m pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src
	cd frontend && pnpm lint && pnpm typecheck
	cd print-agent && $(AGENT_RUN) python -m ruff check . && $(AGENT_RUN) python -m ruff format --check .

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && pnpm exec eslint --fix
	cd print-agent && $(AGENT_RUN) python -m ruff check --fix . && $(AGENT_RUN) python -m ruff format .

migrate:
	cd backend && uv run alembic upgrade head

migration: ## usage: make migration m="add stores"
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

api-client:
	cd backend && uv run python -m mallt.cli openapi > ../frontend/openapi.json
	cd frontend && pnpm api:gen

seed-admin:
	cd backend && uv run python -m mallt.cli seed-admin

# Needs Postgres on localhost:5432 (user postgres / password test), uv, pnpm and nginx. The stack
# (API + web + nginx on :8080) is started and stopped by Playwright via infra/e2e/local-stack.sh.
# Set PLAYWRIGHT_CHROMIUM_PATH to reuse an installed browser; E2E_SKIP_BUILD=1 to skip the build.
e2e:
	cd frontend && pnpm exec playwright test
