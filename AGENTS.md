# AGENTS.md — EchoNotes

Instructions for every AI coding agent (and human) working in this repo. Keep this file short. The details live in the modular docs linked below.

## Project

**EchoNotes** is a web app that turns audio into organized text notes. Projects act as folders. Inside one you upload or record audio, get a transcript (Groq Whisper, or a deterministic `fake` provider), edit, copy or download it (`.md`/`.txt`), attach screenshots (picker or Ctrl+V), and export the project as a ZIP. This is the final project for the AI Dev Tools Zoomcamp 2026.

## Read these docs (modular context)

| Need | Doc |
|---|---|
| What we build, user stories, acceptance criteria, non-goals | [docs/product-spec.md](docs/product-spec.md) |
| API contract (frontend ↔ backend) | [openapi.yaml](openapi.yaml) |
| Who does what (PM, SWE, QA, DevOps agents) and hand-offs | [docs/agent-team.md](docs/agent-team.md) |
| Issues, branches, commits, PRs, definition of done | [docs/process.md](docs/process.md) |
| Components, data model, Transcriber interface | [docs/architecture.md](docs/architecture.md) |
| Test pyramid and commands | [docs/testing.md](docs/testing.md) |
| Environments and Render (planned P3) | [docs/deployment.md](docs/deployment.md) |
| Dev → prod promotion and rollback (planned P3) | [docs/release-process.md](docs/release-process.md) |
| Telemetry, alerts, on-call (planned P4) and privacy rules | [docs/observability.md](docs/observability.md) |
| How AI was used to build this | [docs/ai-usage-report.md](docs/ai-usage-report.md) |

Subagent definitions are in [`.claude/agents/`](.claude/agents/).

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic (from M2), Postgres; managed with **uv**; tested with pytest; linted and formatted with ruff
- **Frontend:** React 19 + TypeScript (strict) + Vite; tested with Vitest + Testing Library (jsdom); linted with oxlint
- **Infra:** Docker / docker compose (M2), GitHub Actions CI, Render dev + prod (M3), OpenTelemetry (M4)

## Repo layout

```
backend/            FastAPI app (app/), tests (tests/), pyproject.toml, uv.lock
frontend/           Vite React TS app (src/), vitest tests next to components
docs/               modular project docs (see table above)
openapi.yaml        API contract
.claude/agents/     subagent definitions (product-manager, software-engineer, qa-engineer, devops-sre)
.github/workflows/  CI (and CD from M3)
prompts/            the prompts given to Claude Code (evidence of AI usage)
```

## Commands

```bash
# backend (from backend/)
uv sync                         # install
uv run uvicorn app.main:app --loop app.event_loop:new_event_loop --reload --port 8000  # --loop: needed on Windows
uv run ruff check . && uv run ruff format --check .
uv run pytest

# frontend (from frontend/)
npm ci
npm run dev                     # http://localhost:5173, proxies /api to :8000
npm run lint && npm run typecheck
npm test
npm run build

# whole system (planned in P2)
docker compose up --build
```

## Coding conventions

- Python: type hints everywhere, small functions, Pydantic models for I/O, ruff (line length 100) as the style authority, `async` endpoints.
- TypeScript: `strict` mode, function components and hooks, no `any`. API types follow `openapi.yaml`.
- Name tests after the behavior or acceptance criterion they cover (`test_create_project_rejects_blank_name`).
- Keep `openapi.yaml`, `.env.example` and the docs in sync with the code in the same PR.

## Always work through GitHub issues

1. No change without an issue (`gh issue view <N>`). Create one through the `product-manager` if it is missing.
2. One issue → one branch `feat/<N>-<slug>` → one PR with `Closes #N`.
3. Commits use Conventional Commits and reference the issue (`Refs #N`).
4. Merge only when CI is green **and** the `qa-engineer` posted an APPROVED report.
5. Close issues with evidence (the PR link, or a comment with the commit SHA for docs-only work).

## Definition of done

Every acceptance criterion has evidence. Tests are written with the code and pass locally and in CI. Lint and type checks are clean. Docs, contract and `.env.example` are updated. There are no secrets and no customer data in code, logs or telemetry. The PR is merged and the issue is closed with evidence. Full version: [docs/process.md](docs/process.md#6-definition-of-done-global).

## Security and privacy rules (non-negotiable)

- **Never commit secrets.** `.env` is git-ignored. Only `.env.example` (no real values) is tracked. Secrets live in GitHub/Render secrets.
- **Never log or send to telemetry** transcript text, titles, user filenames, audio bytes, image bytes, API keys or connection strings. Log IDs, sizes, durations, status codes and provider names only.
- **Never persist raw audio.** Process it in memory or a temp file and discard it in `finally`.
- Validate uploads by size and content type (images by magic bytes).
- Tests and CI never call the real Groq API. Use `TRANSCRIBER_PROVIDER=fake`.
- Don't run destructive git commands (`push --force` to `main`, history rewrites) without explicit human approval.
