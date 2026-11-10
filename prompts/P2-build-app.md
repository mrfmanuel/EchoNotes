You are the tech lead (orchestrator) for EchoNotes. This is prompt 2 of 4: build the FULL application (milestone "M2 App"), its tests and its containerization. Work autonomously through ALL steps below in this single session; do not stop to ask me questions unless you are truly blocked. Everything you write must be in English. Follow AGENTS.md and the modular docs strictly — they are the source of truth (spec: docs/product-spec.md, contract: openapi.yaml, process: docs/process.md, team: docs/agent-team.md).

Setup notes:
- The subagents in `.claude/agents/` are now loaded by name — use `product-manager`, `software-engineer`, `qa-engineer` and `devops-sre` explicitly (not general-purpose stand-ins).
- `.env` exists locally with `GROQ_API_KEY` set. NEVER print, log, echo, or commit its value. Tests and CI always use `TRANSCRIBER_PROVIDER=fake`.
- `prompts/P1-foundation.md` was updated by me to the final text that was actually run, and `prompts/P2-build-app.md` (this prompt) was added; commit both in your first docs commit (`docs: add P2 prompt, sync P1 prompt text`).
- Make is available (`make` on Windows via Git Bash).

## Goal / Definition of done for this prompt
All M2 issues are closed with evidence, and these rubric criteria are fully met:
- **Application (2 pts):** frontend talks to backend, data persists in Postgres, and the whole app runs locally with ONE command: `docker compose up --build` → open http://localhost:8000.
- **Testing (2 pts):** unit AND integration tests exist, run with ONE command (`make test`), and pass — locally and in CI.
- **Containerization (2 pts):** the full system INCLUDING the database runs via Docker Compose with one command; no manual steps (migrations run automatically).

## Work plan

1. **Groom (product-manager):** review all open M2 issues against the spec, confirm acceptance criteria are testable, and set an implementation order. To save time, you MAY group 2–3 tightly related issues into one branch/PR (PR body lists every `Closes #N`), but never mix backend-only refactors with unrelated features. Post a short grooming comment on each M2 issue (order + grouping).

2. **Implement (software-engineer), PR by PR, following docs/process.md.** Suggested order:
   a. DB foundation: SQLAlchemy 2 models (projects, transcripts, screenshots with `bytea`), Alembic migrations, settings via pydantic-settings, session management, `/api/health` checks the DB (US-17 AC2). Single-source the version (fix the QA note: read version from package metadata or one constant, not two places).
   b. Projects API (US-01..04) incl. slug uniqueness and `updated_at` bump rule (US-02 AC3).
   c. Transcriber interface + `fake` + `groq` providers (httpx, timeout, error mapping to 502/504, `verbose_json` for duration), upload validation (type → 415, size → 413), audio never persisted (US-05..07).
   d. Transcript read/edit/delete + download `.md` / `.txt` (US-08..11).
   e. Screenshots: upload, magic-byte validation, 5 MB limit, optional transcript link, serve image, delete (US-12..15).
   f. ZIP export with the exact folder structure from the spec, streamed (US-16).
   g. Frontend: clean, responsive UI (projects list, project page with upload + record + language hint, transcript editor with Copy / Download .md / Download .txt, screenshot gallery with file picker + Ctrl+V paste, export button, loading/error/empty states). Typed API client matching openapi.yaml. Keep it simple but polished (a small CSS design system is enough; no heavy UI framework required).
   h. Observability-ready plumbing (small, used later in P4): JSON structured logging and a request-ID middleware (`X-Request-ID` echoed in responses). Log only IDs, sizes, durations, status codes, provider names — never transcript text, titles, filenames or bytes.

3. **Tests (written with the code in each PR):**
   - Backend unit tests (pytest, SQLite or pure functions, `FakeTranscriber`, Groq client with mocked HTTP via respx) — mark integration tests with `@pytest.mark.integration`.
   - Backend integration tests against REAL Postgres: full API flows (create project → upload audio with fake provider → edit transcript → attach screenshot → export ZIP and assert its file tree), cascade delete, migrations apply cleanly on an empty DB.
   - Frontend component tests (Vitest + Testing Library) for the main components/pages with a mocked API client, covering copy-to-clipboard, download buttons, paste-screenshot handler and error states.
   - A tiny privacy test: run a transcription + export and assert captured logs contain no transcript text or title.
   - `Makefile` targets: `make test` (ONE command: starts a throwaway Postgres via `docker compose -f docker-compose.test.yml` or a compose profile, runs backend unit + integration and frontend tests, tears the DB down, non-zero exit on any failure), `make test-unit`, `make up`, `make down`, `make lint`.
   - CI (`.github/workflows/ci.yml`): add a Postgres service container and run the integration tests too; keep lint/typecheck/build. Add a job that builds the Docker image (no push).

4. **Containerization (devops-sre):**
   - Multi-stage `Dockerfile` at repo root: stage 1 builds the frontend; stage 2 is a slim Python 3.12 image with uv that serves the API AND the built SPA from FastAPI (SPA fallback for client-side routes), runs as a non-root user, honors `$PORT` (default 8000), and runs `alembic upgrade head` before starting uvicorn (entrypoint script). Add a HEALTHCHECK. Add `.dockerignore`.
   - `docker-compose.yml`: `db` (postgres:16 with a named volume and healthcheck) + `app` (depends_on db healthy, env from `.env` with safe defaults so it works WITHOUT a `.env` using the fake provider). One command: `docker compose up --build`.
   - This same image is what P3 deploys to Render, so keep it production-ready.

5. **QA (qa-engineer) on EVERY PR:** check out the branch, run `make test`, verify each acceptance criterion of the linked issues (API calls with curl and/or reading the UI code/tests), post a structured QA report (criterion → evidence → pass/fail) on the PR, and APPROVE or REQUEST CHANGES. Merge only with green CI + QA approval (squash-merge). Close issues with evidence.

6. **Final end-to-end verification (you + qa-engineer):**
   - `docker compose down -v && docker compose up --build -d`, then run a smoke script `scripts/smoke.sh <base-url>` (create this; it's reused in P3 after deploys) that exercises the key journey with the fake provider: health → create project → upload a small generated audio file → get transcript → upload a screenshot → export ZIP and check it's a valid zip. Make it work in Git Bash and Linux (CI).
   - Then do ONE real Groq check locally: restart the app with `TRANSCRIBER_PROVIDER=groq` (key from `.env`) and transcribe a short generated or sample speech clip if you can produce one; if you cannot create a speech audio file, just verify the Groq provider returns a proper error/200 path with a tiny file and tell me to test it by recording from the browser. Do not print the key.
   - Take 3–4 screenshots of the running UI (Playwright via `npx playwright` is acceptable if it installs cleanly; otherwise skip and tell me) and save them in `docs/images/` for the README.
   - `make test` passes, CI is green on main.

7. **Docs (keep honest, mark what's still planned for P3/P4):** update README (real run/test commands, screenshots, architecture diagram, rubric table status), `docs/testing.md` (real pyramid + commands + what each suite covers), `docs/architecture.md` (data model, Transcriber, request flow), `openapi.yaml` (must match the implementation — add a contract test that compares FastAPI's generated paths with openapi.yaml paths, or document any intentional differences), `.env.example`, and append the P2 section to `docs/ai-usage-report.md` (what each agent did, PR list, problems found by QA, what a human must still verify). Close milestone "M2 App" when all its issues are closed.

When done, print a concise summary: PRs merged (with numbers), issues closed, test counts (unit / integration / frontend), the exact commands to run the app and the tests, CI status on main, the result of the real Groq check, and anything I must verify manually in the browser before prompt 3.
