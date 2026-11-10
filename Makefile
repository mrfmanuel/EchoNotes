# EchoNotes developer commands. Works on Linux, macOS and Git Bash on Windows.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

TEST_COMPOSE := docker compose -f docker-compose.test.yml
TEST_DATABASE_URL ?= postgresql+psycopg://echonotes_test:echonotes_test@localhost:55432/echonotes_test

.PHONY: help test test-unit test-backend test-frontend lint up down testdb-up testdb-down

help: ## Show the available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

test: ## Backend unit + integration (throwaway Postgres) and frontend tests; always tears down
	@$(TEST_COMPOSE) up -d --wait testdb
	@status=0; \
	(cd backend && TEST_DATABASE_URL='$(TEST_DATABASE_URL)' TRANSCRIBER_PROVIDER=fake uv run pytest) || status=$$?; \
	if [ $$status -eq 0 ]; then (cd frontend && npm test) || status=$$?; fi; \
	$(TEST_COMPOSE) down -v; \
	exit $$status

test-unit: ## Fast tests without Docker: backend unit tests + frontend tests
	cd backend && TRANSCRIBER_PROVIDER=fake uv run pytest -m "not integration"
	cd frontend && npm test

lint: ## ruff check + format check, oxlint, tsc
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint && npm run typecheck

up: ## Build and start app + Postgres (http://localhost:8000), wait until healthy
	docker compose up --build -d --wait

down: ## Stop the whole stack (keeps the database volume; use `docker compose down -v` to wipe)
	docker compose down
