# Testing Strategy

> Status: implemented (M2 #23; telemetry tests #29, responder tests #32). Every suite below exists, runs with one command (`make test`) and runs in CI on every PR.

## Test pyramid

Counts as of #47. `pytest --collect-only -q` and `npx vitest run` print the current numbers.

| Level | Tests | Tooling | What it covers | Runs in |
|---|---:|---|---|---|
| Backend unit | 456 | `pytest`, AnyIO, in-memory SQLite (`aiosqlite`), `httpx2.ASGITransport`, fake/stub transcribers | Settings, slugs, upload and image validation, transcript formatting, export plan, every API endpoint (happy path + 4xx/5xx shapes), request IDs and JSON logs, Groq client with a mocked HTTP layer, SPA serving, event loop selection (#41), Alembic CLI logs as JSON (#41), **contract test** (`openapi.yaml` ↔ FastAPI), **OpenTelemetry** spans/metrics/logs with in-memory exporters and **telemetry privacy** tests (#29) | every PR (`backend` job), `make test`, `make test-unit` |
| Backend integration | 38 | `pytest -m integration`, real Postgres 16, Alembic migrations, `httpx2.ASGITransport` | Migrations (empty DB → head, downgrade/upgrade round trip, models == migrations), cascades and `SET NULL` on Postgres, every API flow with persistence (bytea, `timestamptz`, unique slugs), export ZIP tree, **full flow** and **privacy** test | every PR (`backend` job with a `postgres:16` service), `make test` |
| Frontend component | 136 | Vitest + Testing Library + jsdom, mocked API client | Pages and components: projects, upload/record, transcript editor (copy, download, unsaved changes), screenshots (picker, Ctrl+V paste, link, gallery), export, API client errors, build-info footer | every PR (`frontend` job), `make test`, `make test-unit` |
| On-call responder | 83 | `pytest` (stdlib + PyYAML/jsonschema via `uv run`), a **stub agent** instead of `claude`, throwaway git repos | Webhook dedupe and malformed input, evidence collection and scrubbing, response schema, every autonomy-policy check (paths, lines, removed tests, secrets, symlinks, reproduction, hooks/config tampering, commit = evaluated diff), the full pipeline with publish/deploy stubs, CLI-compatible schema (#32) | every PR (`incident-response` job), `make test`, `make test-unit`, `make test-responder` |
| End-to-end smoke | 1 script (8 steps) | `scripts/smoke.sh` (bash + curl + Python 3) against a running stack | Key journey: health → SPA → create project → upload audio → transcript → screenshot → export ZIP → delete | every PR (CI `docker` job, compose stack); after every deploy (M3) |

### Backend suites in detail

| File | Tests | Covers |
|---|---:|---|
| `integration/test_full_flow_pg.py` | 2 | create project → upload audio (fake) → edit transcript → attach a linked screenshot → export ZIP (exact tree, edited text in `.md`/`.txt`, README links) → delete project (no `project`/`transcript`/`screenshot` rows left). The privacy test runs the same flow at `LOG_LEVEL=DEBUG` and asserts no stdout/stderr line or log record contains the project name, transcript title, transcript text or any filename |
| `integration/test_migrations.py` | 3 | `alembic upgrade head` on a brand-new empty schema (tables created, autogenerate diff empty, JSON migration logs without the URL); `downgrade base` → `upgrade head`; migrated schema == models |
| `integration/test_cascade_pg.py`, `test_screenshots_export_pg.py` | 11 | `ON DELETE CASCADE` (project → transcripts, screenshots), `SET NULL` (transcript → screenshot link), bytea round trip at 5 MiB, export tree on Postgres |
| `integration/test_projects_pg.py`, `test_transcriptions_pg.py`, `test_transcripts_manage_pg.py`, `test_health_pg.py` | 22 | Endpoint behavior on Postgres: slugs, ordering, `updated_at` bumps, provider errors store nothing, health `database: ok` |
| `unit/test_contract.py` | 10 | Same `(path, method)` set in `openapi.yaml` and `app.openapi()` (only `/api/*`; path params normalized), same `operationId`s, same success codes, every documented error code is declared, `/api/health` body validates against the `Health` schema |
| `unit/test_event_loop.py`, `unit/test_migration_logs.py`, `unit/test_logging.py` | 16 | #41: selector loop on Windows (monkeypatched `sys.platform`, passes on Linux), `--loop app.event_loop:new_event_loop` resolves, Proactor warning; Alembic CLI logs are JSON; no `color_message`/ANSI in logs |

### Intentional differences between `openapi.yaml` and the FastAPI schema

The contract test allows exactly one difference: FastAPI adds an automatic `422` response to every operation that has a path parameter (a malformed UUID fails request validation). The contract documents `422` only where a body or query value can be invalid. Everything else (paths, methods, `operationId`s, success codes, documented error codes) must match.

## Commands

```bash
# Everything with one command (repo root). Starts a throwaway Postgres 16 on host port 55432
# (tmpfs, compose project "echonotes-test"), runs backend unit + integration tests, then the
# frontend tests even if the backend failed, prints both exit codes, ALWAYS runs `down -v`
# (also on failure and Ctrl+C), and exits non-zero if either suite failed.
# On a fresh clone `make test`, `make test-unit` and `make lint` first run `npm ci` in frontend/
# (only when frontend/node_modules is missing); uv creates backend/.venv on its own.
make test

make test-unit             # no Docker: backend `pytest -m "not integration"` + frontend tests
make lint                  # ruff check + format check, oxlint, tsc
make up && make smoke      # end-to-end smoke test against the compose stack (see below)

# backend only (from backend/)
uv run pytest                          # unit tests; integration tests SKIP without TEST_DATABASE_URL
uv run pytest -m "not integration"     # unit tests only
uv run pytest -m integration           # integration only (needs TEST_DATABASE_URL)
docker compose -f ../docker-compose.test.yml up -d --wait testdb
TEST_DATABASE_URL=postgresql+psycopg://echonotes_test:echonotes_test@localhost:55432/echonotes_test \
  uv run pytest                        # unit + integration against the running test DB
docker compose -f ../docker-compose.test.yml down -v

# frontend only (from frontend/)
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
  1. `GET /api/health` → 200 and `database: ok`, retried every 3 s until `SMOKE_HEALTH_TIMEOUT` (cold starts). `commit` and `environment` must be non-empty; the line prints the 7-char commit and the environment. With `SMOKE_EXPECT_COMMIT` set, a different `commit` fails the run (deploy verification, #47).
  2. `GET /` and a client route → 200 `index.html`; `GET /api/<unknown>` → 404.
  3. `POST /api/projects` with a unique, clearly identifiable name `smoke-test-<UTC timestamp>-<pid>` → 201.
  4. `POST /api/projects/{id}/transcriptions` with the WAV → 201 (prints provider and duration only).
  5. `GET /api/transcriptions/{id}` → 200; `text` must be non-empty (prints its length only).
  6. `POST /api/projects/{id}/screenshots` with the PNG and `transcript_id` → 201, linked.
  7. `GET /api/projects/{id}/export` → 200 `application/zip`; Python `zipfile.testzip()` passes and the tree has `<slug>/README.md`, `<slug>/transcripts/*.md`, `<slug>/transcripts/*.txt` and `<slug>/screenshots/01-*.png`.
  8. `DELETE /api/projects/{id}` → 204. If an earlier step fails (or the run is interrupted), the `EXIT` trap still deletes the project, so dev/prod stay clean. `SMOKE_KEEP=1` is the only way to skip the cleanup. Verified for #47 by forcing a failure at step 4 (provider `groq` pointed at an unreachable `GROQ_BASE_URL` → 502): the trap printed `cleanup: deleted project <id> (HTTP 204)` and `GET /api/projects` listed no `smoke-test-*` project.
- **Privacy:** prints only status codes, IDs, sizes, counts and timings, never response bodies, transcript text or secrets (`user:pass@` in the URL is masked).

| Variable | Default | Effect |
|---|---|---|
| `SMOKE_HEALTH_TIMEOUT` | `90` | Seconds to keep retrying `/api/health` |
| `SMOKE_REQUEST_TIMEOUT` | `120` | Max seconds per request (the upload waits for the provider) |
| `SMOKE_ALLOW_EMPTY_TEXT` | unset | `1` accepts an empty transcript (real Groq may return nothing for silent audio) |
| `SMOKE_SKIP_SPA` | unset | `1` skips the SPA checks (API-only server, e.g. `uvicorn` without `STATIC_DIR`) |
| `SMOKE_KEEP` | unset | `1` keeps the smoke project for debugging (no delete) |
| `SMOKE_EXPECT_COMMIT` | unset | Full SHA; the health step fails unless `/api/health` reports exactly this `commit` |

## Deploy script tests (`scripts/deploy.sh`, #25 #26 #27)

```bash
bash scripts/tests/test_deploy.sh    # ~40 s, Linux or Git Bash; needs curl + Python 3
```

- Runs `scripts/deploy.sh` and `scripts/resolve-commit.sh` against `scripts/tests/deploy_mock.py`, a local stub of the Render deploy hook and `/api/health` on a free `127.0.0.1` port; `scripts/tests/fake_smoke.sh` stands in for `smoke.sh`. **Never calls the real Render hooks.**
- Covers: success (health 503 → old commit → new commit), hook `202` retried with backoff, `202` beyond `DEPLOY_HOOK_WAIT`, `404` (unknown SHA / bad key), other status, unreachable hook, verify timeout, smoke failure, environment mismatch, invalid SHA, missing hook URL, `::add-mask::`, the hook key never appearing in output or job summaries, and SHA resolution (short → full, only commits on `origin/main`).
- Not part of `ci.yml` (kept unchanged); run it locally whenever `deploy.sh`, `resolve-commit.sh` or the deploy workflows change.

## Markers and layout

- **Marker `integration`** (registered in `backend/pyproject.toml`; `--strict-markers` is on). Integration modules set `pytestmark = pytest.mark.integration`. When `TEST_DATABASE_URL` is unset they are **skipped** with the reason "set TEST_DATABASE_URL (or run `make test`)", so `uv run pytest` works without Docker.
- **Async tests** use the AnyIO pytest plugin (`pytest.mark.anyio`). On Windows the `anyio_backend` fixture uses a selector loop, because psycopg's async mode cannot use the Proactor loop.
- `backend/tests/unit/`: each test gets a fresh in-memory SQLite schema (`sqlite+aiosqlite`, `StaticPool`, `PRAGMA foreign_keys=ON`, `Base.metadata.create_all`) and the app with `get_session` overridden through `app.dependency_overrides`.
- `backend/tests/integration/`: read `TEST_DATABASE_URL`, run `alembic upgrade head` once per session through the real `alembic.ini`/`env.py` (URL from `DATABASE_URL` via settings), and `TRUNCATE` all tables before each test.
- Shared helpers: `tests/image_utils.py` (image payloads with real magic bytes, ZIP reader), `tests/transcription_utils.py` (stub transcribers, upload helper), `tests/project_utils.py` (seed rows), `tests/log_utils.py` (parse JSON log lines).
- An autouse fixture clears the backend env vars and the cached settings/engine for every test, so a developer's shell or `.env` never leaks into tests.
- Frontend tests sit next to the code (`*.test.ts(x)`). `src/test/setup.ts` runs after every test: Testing Library `cleanup`, real timers, `vi.restoreAllMocks()` and `vi.unstubAllGlobals()`, so no stubbed global (`MediaRecorder`, `window.confirm`, ...) leaks into the next test.

## CI jobs (`.github/workflows/ci.yml`)

| Job | Steps |
|---|---|
| `backend` | `postgres:16` service container + `TEST_DATABASE_URL`, `uv sync --frozen`, ruff check, ruff format check, `pytest` (unit + integration) |
| `frontend` | `npm ci`, oxlint, `tsc -b`, `vitest run`, `vite build` |
| `docker` | build the image, check non-root/no Node/no uv, `docker compose up --wait`, `scripts/smoke.sh http://localhost:8000`, logs on failure, `down -v` |

## Rules

- Tests are written **with** the code, in the same PR, and each acceptance criterion maps to at least one test named after it.
- Tests and CI never call the real Groq API (`TRANSCRIBER_PROVIDER=fake`; the Groq client is tested with a mocked HTTP layer).
- Tests never assert on log lines that contain user content, because there must not be any. The privacy test enforces it for the full flow.
- A flaky test is a bug: fix the cause (for example the Ctrl+V paste listener is registered in a layout effect so it is attached as soon as the gallery is visible), never add retries.
