# Single entry point for every dev task. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

# Ports and DB settings come from .env (copied from .env.example on first setup).
-include .env
export

BACKEND  := cd backend &&
FRONTEND := cd frontend &&
SCRAPER  := cd scraper &&

.PHONY: help setup env db-up db-down db-reset dev dev-backend dev-frontend migrate migration \
        gen-api test test-backend test-scraper test-frontend lint lint-backend lint-scraper \
        lint-frontend format build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(firstword $(MAKEFILE_LIST)) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

setup: env ## Install Python (uv workspace) and frontend dependencies from lockfiles
	uv sync --locked --all-packages
	$(FRONTEND) npm ci

db-up: env ## Start local Postgres and wait until it is healthy
	docker compose up -d --wait db

db-down: ## Stop local Postgres (data is kept)
	docker compose down

db-reset: ## Delete the local database volume and start fresh
	docker compose down -v
	$(MAKE) db-up migrate

dev: ## Run backend and frontend together (Ctrl+C stops both)
	@$(MAKE) -j2 --no-print-directory dev-backend dev-frontend

dev-backend:
	$(BACKEND) uv run uvicorn app.main:app --reload --port $(BACKEND_PORT)

dev-frontend:
	$(FRONTEND) npm run dev

migrate: ## Apply database migrations
	$(BACKEND) uv run alembic upgrade head

migration: ## Create a migration from model changes: make migration m="add courses"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	$(BACKEND) uv run alembic revision --autogenerate -m "$(m)"

gen-api: ## Regenerate frontend API types from the backend OpenAPI schema
	$(BACKEND) uv run python -m scripts.export_openapi ../openapi.json
	$(FRONTEND) npm run gen-api

test: test-backend test-scraper test-frontend ## Run all tests

test-backend:
	$(BACKEND) uv run pytest

test-scraper:
	$(SCRAPER) uv run pytest

test-frontend:
	$(FRONTEND) npm test

lint: lint-backend lint-scraper lint-frontend ## Lint, format-check and type-check everything

lint-backend:
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts

lint-scraper:
	$(SCRAPER) uv run ruff check . && uv run ruff format --check . && uv run mypy oxy_scraper tests

lint-frontend:
	$(FRONTEND) npm run lint && npm run typecheck

format: ## Auto-format backend, scraper and frontend code
	$(BACKEND) uv run ruff check --fix . && uv run ruff format .
	$(SCRAPER) uv run ruff check --fix . && uv run ruff format .
	$(FRONTEND) npm run format

build: ## Production build of the frontend
	$(FRONTEND) npm run build
