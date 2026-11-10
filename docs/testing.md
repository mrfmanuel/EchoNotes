# Testing Strategy

> Status: M2 in progress. The integration harness (throwaway Postgres, `integration` marker, `make test`, CI service container) exists since PR-A (#9/#16/#35, Refs #23). Cross-feature tests arrive with #23's completion PR.

## Test pyramid

| Level | Tooling | Scope | Runs in |
|---|---|---|---|
| Backend unit | `pytest`, SQLite in-memory, `FakeTranscriber` | Services, slugging, validation, export builder, transcriber factory, Groq client with mocked HTTP (`respx`) | every PR |
| Backend integration | `pytest -m integration` + real Postgres 16 (service container in CI, `docker-compose.test.yml` locally) + `httpx2.AsyncClient` | Migrations, API endpoints end to end with persistence, cascades and ZIP structure | every PR |
| Frontend unit/component | Vitest + Testing Library + jsdom | Components and pages with a mocked API client | every PR |
| End-to-end smoke | `scripts/smoke.sh` (bash + curl + Python 3) against a running stack | Key journey: health → SPA → create project → upload audio → transcript → screenshot → export ZIP → delete | every PR (CI `docker` job, compose stack); after every deploy (M3) |

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

## End-to-end smoke test (`scripts/smoke.sh`, #24)

```bash
make up && make smoke                          # compose stack on http://localhost:8000
scripts/smoke.sh http://localhost:8000         # same thing, any base URL
make smoke SMOKE_URL=https://<dev-or-prod-url> # post-deploy check (M3)
```

- **Needs:** bash, `curl` and Python 3 (`python3`, or `python` when `python3` is missing or is the Windows Store stub). Works on Linux CI and Git Bash on Windows. No binary fixtures: the script generates a 1 s silent WAV and a 4x4 PNG in a `mktemp -d` directory that a `trap` removes on exit.
- **Steps** (one `PASS`/`FAIL` line each, with HTTP status and timing; exits non-zero at the first failure, `2` without an argument):
  1. `GET /api/health` → 200 and `database: ok`, retried every 3 s until `SMOKE_HEALTH_TIMEOUT` (cold starts).
  2. `GET /` and a client route → 200 `index.html`; `GET /api/<unknown>` → 404.
  3. `POST /api/projects` with a unique name `smoke-<UTC timestamp>-<pid>` → 201.
  4. `POST /api/projects/{id}/transcriptions` with the WAV → 201 (prints provider and duration only).
  5. `GET /api/transcriptions/{id}` → 200; `text` must be non-empty (prints its length only).
  6. `POST /api/projects/{id}/screenshots` with the PNG and `transcript_id` → 201, linked.
  7. `GET /api/projects/{id}/export` → 200 `application/zip`; Python `zipfile.testzip()` passes and the tree has `<slug>/README.md`, `<slug>/transcripts/*.md`, `<slug>/transcripts/*.txt` and `<slug>/screenshots/01-*.png`.
  8. `DELETE /api/projects/{id}` → 204. If an earlier step fails, the `EXIT` trap still deletes the project, so dev/prod stay clean.
- **Privacy:** prints only status codes, IDs, sizes, counts and timings, never response bodies, transcript text or secrets (`user:pass@` in the URL is masked).

| Variable | Default | Effect |
|---|---|---|
| `SMOKE_HEALTH_TIMEOUT` | `90` | Seconds to keep retrying `/api/health` |
| `SMOKE_REQUEST_TIMEOUT` | `120` | Max seconds per request (the upload waits for the provider) |
| `SMOKE_ALLOW_EMPTY_TEXT` | unset | `1` accepts an empty transcript (real Groq may return nothing for silent audio) |
| `SMOKE_SKIP_SPA` | unset | `1` skips the SPA checks (API-only server, e.g. `uvicorn` without `STATIC_DIR`) |
| `SMOKE_KEEP` | unset | `1` keeps the smoke project for debugging (no delete) |

## Backend layout and fixtures

- `backend/tests/unit/`: fast tests. Each test gets a fresh in-memory SQLite schema (`sqlite+aiosqlite`, `StaticPool`, `PRAGMA foreign_keys=ON`, `Base.metadata.create_all`) and the app with `get_session` overridden through `app.dependency_overrides`. Async tests use the AnyIO pytest plugin (`pytest.mark.anyio`).
- `backend/tests/integration/`: modules set `pytestmark = pytest.mark.integration` (the marker is registered in `pyproject.toml`, `--strict-markers` is on). They read `TEST_DATABASE_URL`, run `alembic upgrade head` once per session through the real `alembic.ini`/`env.py` (URL taken from `DATABASE_URL` via settings), and `TRUNCATE` all tables before each test.
- An autouse fixture clears the backend env vars and the cached settings/engine for every test, so a developer's shell or `.env` never leaks into tests.
- CI (`.github/workflows/ci.yml`) runs the backend job with a `postgres:16` service container and `TEST_DATABASE_URL`, so unit **and** integration tests run on every PR.

## Rules

- Tests are written **with** the code, in the same PR, and each acceptance criterion maps to at least one test.
- CI never calls the real Groq API (`TRANSCRIBER_PROVIDER=fake`).
- Tests never assert on log lines that contain user content, because there must not be any.
