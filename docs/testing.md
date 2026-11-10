# Testing Strategy

> Status: M2 in progress. The integration harness (throwaway Postgres, `integration` marker, `make test`, CI service container) exists since PR-A (#9/#16/#35, Refs #23). Cross-feature tests arrive with #23's completion PR.

## Test pyramid

| Level | Tooling | Scope | Runs in |
|---|---|---|---|
| Backend unit | `pytest`, SQLite in-memory, `FakeTranscriber` | Services, slugging, validation, export builder, transcriber factory, Groq client with mocked HTTP (`respx`) | every PR |
| Backend integration | `pytest -m integration` + real Postgres 16 (service container in CI, `docker-compose.test.yml` locally) + `httpx2.AsyncClient` | Migrations, API endpoints end to end with persistence, cascades and ZIP structure | every PR |
| Frontend unit/component | Vitest + Testing Library + jsdom | Components and pages with a mocked API client | every PR |
| End-to-end smoke (optional) | Playwright or `curl` script against `docker compose` | Key journey: create project → upload → transcript → export | planned M2/M3 |

## Commands

```bash
# everything with one command (repo root): starts a throwaway Postgres 16 on host port 55432
# (tmpfs, project "echonotes-test"), runs backend unit + integration and frontend tests,
# always tears it down, and exits non-zero on any failure
make test

make test-unit             # no Docker: backend `pytest -m "not integration"` + frontend tests
make lint                  # ruff check + format check, oxlint, tsc

# backend only
cd backend
uv run pytest                          # unit tests; integration tests SKIP without TEST_DATABASE_URL
uv run pytest -m "not integration"     # unit tests only
TEST_DATABASE_URL=postgresql+psycopg://echonotes_test:echonotes_test@localhost:55432/echonotes_test   uv run pytest                        # unit + integration against a running test DB

# frontend
cd frontend
npm test                   # vitest run
```

## Backend layout and fixtures

- `backend/tests/unit/`: fast tests. Each test gets a fresh in-memory SQLite schema (`sqlite+aiosqlite`, `StaticPool`, `PRAGMA foreign_keys=ON`, `Base.metadata.create_all`) and the app with `get_session` overridden through `app.dependency_overrides`. Async tests use the AnyIO pytest plugin (`pytest.mark.anyio`).
- `backend/tests/integration/`: modules set `pytestmark = pytest.mark.integration` (the marker is registered in `pyproject.toml`, `--strict-markers` is on). They read `TEST_DATABASE_URL`, run `alembic upgrade head` once per session through the real `alembic.ini`/`env.py` (URL taken from `DATABASE_URL` via settings), and `TRUNCATE` all tables before each test.
- An autouse fixture clears the backend env vars and the cached settings/engine for every test, so a developer's shell or `.env` never leaks into tests.
- CI (`.github/workflows/ci.yml`) runs the backend job with a `postgres:16` service container and `TEST_DATABASE_URL`, so unit **and** integration tests run on every PR.

## Rules

- Tests are written **with** the code, in the same PR, and each acceptance criterion maps to at least one test.
- CI never calls the real Groq API (`TRANSCRIBER_PROVIDER=fake`).
- Tests never assert on log lines that contain user content, because there must not be any.
