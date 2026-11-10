You are the tech lead for my AI Dev Tools Zoomcamp 2026 final project. Work autonomously through ALL steps below in this single session; do not stop to ask me questions unless you are truly blocked (e.g. missing credentials). Make sensible decisions and record them in docs. Everything you write (code, docs, commits, issues) must be in English.

Context:
- Working directory: this folder (Windows machine, use Git Bash-compatible commands). It is currently empty except `course-reference/` (course rubric + module notes — read `course-reference/project-README.md` FIRST, it is the grading rubric) and `prompts/` (my prompts to you; keep them in the repo as evidence of AI usage).
- This is prompt 1 of 4. P1 = foundation (spec, tracker, context, agent team, scaffolding, CI). P2 = build the full app + tests + Docker. P3 = deploy to Render with CI/CD dev/prod + rollback. P4 = observability, alerting, on-call responder agent. Do NOT implement application features in this prompt beyond a minimal skeleton.
- GitHub user: mrfmanuel. `gh` CLI is installed and authenticated.

## Product idea (turn this into a proper spec)
"EchoNotes" — a small web app to turn audio into organized text notes.
- Projects act as folders: create, rename, delete, list projects.
- Inside a project: upload an audio file (mp3, wav, m4a, ogg, webm; max 25 MB) OR record from the browser microphone (MediaRecorder), and get a transcript.
- Transcription goes through a pluggable `Transcriber` interface: `groq` provider (Groq Whisper API, OpenAI-compatible endpoint, model `whisper-large-v3-turbo` — verify against current Groq docs) for real use, and a deterministic `fake` provider for tests/CI/local dev without a key. Optional language hint (auto / en / es / pt).
- Transcript view: edit title and text, copy to clipboard, download as `.md` or `.txt`.
- Screenshots: attach images (png/jpg/webp, max 5 MB) to a project, by file picker or by pasting from the clipboard (Ctrl+V); optional link to a specific transcript; thumbnail gallery; delete.
- Export a whole project as a ZIP with a folder structure: `<project-slug>/README.md` (index), `transcripts/*.md` and `*.txt`, `screenshots/*`.
- Privacy: raw audio is NOT persisted after transcription; transcript text and file contents must never be written to logs/telemetry.
- Non-goals: user accounts/auth, multi-tenant sharing, real-time streaming transcription, speaker diarization, mobile apps.
- Persistence: Postgres (SQLite allowed only for fast unit tests). Images stored in the DB (bytea) because the deploy target (Render) has ephemeral disk.
- Health endpoint `GET /api/health`. In production the FastAPI app serves the built React frontend (single container/image).

## Tasks for this prompt

1. **Git + GitHub**: `git init` (branch `main`), create a `.gitignore` (Python, Node, `.env`, `course-reference/`), create a PUBLIC GitHub repo `mrfmanuel/echonotes` with `gh repo create`, and push.

2. **Problem description**: `README.md` with: the problem, who it is for, functionality, expected behavior, architecture overview (short), how to run locally (placeholder commands that P2 will make real: `docker compose up --build`), how to run tests, links to all docs, and a "Course rubric mapping" table (criterion → where the evidence is). Keep the README honest: mark items that come in later prompts as "planned".

3. **Product spec**: `docs/product-spec.md` with problem, personas, user stories, acceptance criteria per story (Given/When/Then), non-goals, constraints, and the key user journey ("upload audio → transcript visible → export"). Also `openapi.yaml` (OpenAPI 3.1) as the contract between frontend and backend covering projects, transcriptions, screenshots, exports, health.

4. **Public task tracker (GitHub Issues)**:
   - Create labels (e.g. `type:feature`, `type:test`, `type:infra`, `type:docs`, `area:backend`, `area:frontend`, `area:devops`, `agent:pm`, `agent:swe`, `agent:qa`) and milestones `M1 Foundation`, `M2 App`, `M3 Deploy & CI/CD`, `M4 Observability & On-call`.
   - Create one issue per user story / technical task for ALL milestones (including future work for P2–P4: Docker Compose, integration tests, Render dev/prod, rollback, OpenTelemetry, alert, on-call responder). Every issue must have: context, acceptance criteria as a checklist, definition of done, and links to the spec section.
   - If `gh` has the `project` scope, also create a public GitHub Project board "EchoNotes" and add the issues; if not, skip it and mention it in your final summary.
   - Close the M1 issues you complete in this prompt with a comment describing what was done (evidence that agents use the tracker). Reference issue numbers in commit messages (`Refs #N` / `Closes #N`).

5. **Agent team** (Claude Code subagents in `.claude/agents/`):
   - `product-manager.md` — owns the spec and backlog, writes/grooms issues and acceptance criteria, never writes code.
   - `software-engineer.md` — implements exactly one issue per branch (`feat/<issue>-<slug>`), writes tests with the code, opens a PR with `Closes #N`.
   - `qa-engineer.md` — independently verifies a PR/issue against its acceptance criteria, runs the test suite, posts a QA report as an issue/PR comment, and may reject.
   - `devops-sre.md` — owns Docker, CI/CD, deployment, observability, alerts and the on-call runbooks.
   - `docs/agent-team.md` — roles, responsibilities, hand-offs, the workflow (PM grooms → SWE implements on branch → QA verifies → merge when CI is green → issue closed with evidence), and how the main session (tech lead/orchestrator) dispatches them. Include a simple diagram (Mermaid).

6. **Context management**: `AGENTS.md` (project overview, stack, repo layout, commands, coding conventions, definition of done, "always work through GitHub issues", security rules like never commit secrets / never log transcript text) that POINTS to modular docs: `docs/product-spec.md`, `docs/agent-team.md`, `docs/process.md` (branching, PRs, commit conventions, issue workflow), `docs/architecture.md`, `docs/testing.md`, `docs/deployment.md`, `docs/release-process.md`, `docs/observability.md`, `docs/ai-usage-report.md` (create the later ones as short stubs marked "planned in P2/P3/P4"). Create `CLAUDE.md` containing just `@AGENTS.md` plus one line explaining it imports AGENTS.md.

7. **Skeleton + CI**:
   - `backend/` (Python 3.12, FastAPI, managed with `uv`, pytest, ruff) with only `/api/health` and one passing test.
   - `frontend/` (Vite + React + TypeScript, Vitest + Testing Library) with a placeholder page and one passing test.
   - `.github/workflows/ci.yml`: on pull_request and push to main → ruff + backend tests, frontend lint/typecheck + tests, frontend build. Use caching. Make sure it passes on GitHub.
   - `.env.example` with all expected variables (`DATABASE_URL`, `TRANSCRIBER_PROVIDER=fake`, `GROQ_API_KEY=`, etc.).

8. **Use the workflow you just defined**: do steps 7 on a branch with a PR (`Closes #N`), wait for CI to go green (`gh pr checks --watch`), have the qa-engineer subagent post a QA comment on the PR, then squash-merge. Docs-only work may go directly to main.

9. Start `docs/ai-usage-report.md`: tools used (Claude Code + Claude Cowork for planning/review), this prompt's summary, what the agents did, what a human verified.

When done, print a concise summary: repo URL, issue/milestone counts, Project board URL (or why skipped), CI status, and anything I must do manually before prompt 2.
