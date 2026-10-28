# Single entry point for dev tasks (see AGENTS.md §4).
SHELL := /bin/bash

# Test databases come from `docker compose --profile test` (ports 55432 / 56379).
# Override to use your own, e.g. `make test TEST_DATABASE_URL=postgresql+asyncpg://...`.
# Set TEST_DB_EXTERNAL=1 to skip starting the compose test containers.
TEST_DATABASE_URL ?= postgresql+asyncpg://postgres:test@localhost:55432/mallt_test
TEST_REDIS_URL ?= redis://localhost:56379/15
export TEST_DATABASE_URL TEST_REDIS_URL

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

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src
	cd frontend && pnpm lint && pnpm typecheck

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && pnpm exec eslint --fix

migrate:
	cd backend && uv run alembic upgrade head

migration: ## usage: make migration m="add stores"
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

api-client:
	cd backend && uv run python -m mallt.cli openapi > ../frontend/openapi.json
	cd frontend && pnpm api:gen

seed-admin:
	cd backend && uv run python -m mallt.cli seed-admin

e2e:
	cd frontend && pnpm exec playwright test
