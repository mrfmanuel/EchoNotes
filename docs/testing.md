# Testing Strategy

> Status: the M1 skeleton has one backend test and one frontend test running in CI. The full pyramid is **planned in P2 (M2 App)**.

## Test pyramid

| Level | Tooling | Scope | Runs in |
|---|---|---|---|
| Backend unit | `pytest`, SQLite in-memory, `FakeTranscriber` | Services, slugging, validation, export builder, transcriber factory, Groq client with mocked HTTP (`respx`) | every PR |
| Backend integration | `pytest` + real Postgres (service container in CI, `docker compose` locally) + `httpx.AsyncClient` | API endpoints end to end with persistence, cascades and ZIP structure | every PR (planned M2) |
| Frontend unit/component | Vitest + Testing Library + jsdom | Components and pages with a mocked API client | every PR |
| End-to-end smoke (optional) | Playwright or `curl` script against `docker compose` | Key journey: create project → upload → transcript → export | planned M2/M3 |

## Commands

```bash
# backend
cd backend
uv run pytest              # all tests
uv run pytest -m "not integration"   # fast unit tests only (planned marker)

# frontend
cd frontend
npm test                   # vitest run

# everything with one command (planned in P2)
make test                  # or: docker compose run --rm tests
```

## Rules

- Tests are written **with** the code, in the same PR, and each acceptance criterion maps to at least one test.
- CI never calls the real Groq API (`TRANSCRIBER_PROVIDER=fake`).
- Tests never assert on log lines that contain user content, because there must not be any.
