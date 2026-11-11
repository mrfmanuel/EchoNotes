# EchoNotes developer commands. Works on Linux, macOS and Git Bash on Windows.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

TEST_COMPOSE := docker compose -f docker-compose.test.yml
SMOKE_URL ?= http://localhost:8000
# Host ports come from the environment (docker-compose.yml defaults: 8000 / 3000), e.g.
# `APP_PORT=8001 GRAFANA_PORT=3001 make obs-up`. Only used here to print the URLs.
SHOW_APP_PORT = $(or $(APP_PORT),8000)
SHOW_GRAFANA_PORT = $(or $(GRAFANA_PORT),3000)
# Observability stack (#30): the `observability` profile adds the lgtm container and points the
# app's OTLP exporter at it. Plain `docker compose up` stays without telemetry.
OBS_COMPOSE := OBS_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability
TEST_DATABASE_URL ?= postgresql+psycopg://echonotes_test:echonotes_test@localhost:55432/echonotes_test

.PHONY: help test test-unit test-backend test-frontend lint up down smoke testdb-up testdb-down \
	obs-up obs-down obs-rebuild-app

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

obs-up: ## App + Postgres + Grafana LGTM (Collector, Prometheus, Loki, Tempo); prints the URLs
	GIT_SHA=$$(git rev-parse HEAD 2>/dev/null || echo unknown) $(OBS_COMPOSE) up --build -d --wait
	@echo "App:       http://localhost:$(SHOW_APP_PORT)"
	@echo "Grafana:   http://localhost:$(SHOW_GRAFANA_PORT)  (admin/admin, local only)"
	@echo "Dashboard: http://localhost:$(SHOW_GRAFANA_PORT)/d/echonotes-journey"

# Rebuild ONLY the app of a running obs stack (same COMPOSE_PROJECT_NAME / ports), keeping the
# OTLP endpoint. A plain `docker compose up --build app` would turn telemetry off, the alert would
# go NoData -> OK and look like a recovery.
obs-rebuild-app: ## Rebuild and restart only the app of the obs stack, telemetry kept on
	GIT_SHA=$$(git rev-parse HEAD 2>/dev/null || echo unknown) $(OBS_COMPOSE) up --build -d --wait app
	@echo "App: http://localhost:$(SHOW_APP_PORT)  (exports to lgtm:4318)"

obs-down: ## Stop app, Postgres and the observability stack (keeps the database volume)
	$(OBS_COMPOSE) down
