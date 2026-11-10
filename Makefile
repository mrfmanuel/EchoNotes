# EchoNotes developer commands. Works on Linux, macOS and Git Bash on Windows.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

TEST_COMPOSE := docker compose -f docker-compose.test.yml
SMOKE_URL ?= http://localhost:8000
TEST_DATABASE_URL ?= postgresql+psycopg://echonotes_test:echonotes_test@localhost:55432/echonotes_test

.PHONY: help test test-unit test-backend test-frontend lint up down smoke testdb-up testdb-down

help: ## Show the available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

# One command for everything (#23). The EXIT trap always removes the throwaway database, also
# when `up` fails or on Ctrl+C (INT/TERM exit through the trap). The frontend tests run even
# if the backend tests failed, both results are printed, and the exit code is non-zero if
# either suite failed.
test: ## Backend unit + integration (throwaway Postgres) and frontend tests; always tears down
	@trap '$(TEST_COMPOSE) down -v' EXIT; \
	trap 'exit 130' INT TERM; \
	$(TEST_COMPOSE) up -d --wait testdb; \
	backend=0; frontend=0; \
	(cd backend && TEST_DATABASE_URL='$(TEST_DATABASE_URL)' TRANSCRIBER_PROVIDER=fake uv run pytest) || backend=$$?; \
	(cd frontend && npm test) || frontend=$$?; \
	echo "make test: backend (unit + integration) exit $$backend, frontend exit $$frontend"; \
	[ $$backend -eq 0 ] && [ $$frontend -eq 0 ]

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

smoke: ## End-to-end smoke test of the key journey against SMOKE_URL (default http://localhost:8000)
	bash scripts/smoke.sh '$(SMOKE_URL)'
