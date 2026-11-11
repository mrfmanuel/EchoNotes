# AI Usage Report

How AI tools were used to build EchoNotes, what the agents did, and what a human verified. This report is updated after each prompt (P1–P4). The prompts themselves are stored in [`prompts/`](../prompts/).

## Tools

| Tool | Used for |
|---|---|
| **Claude Code** (CLI, model Claude Opus) | Main "tech lead" session: writes the spec, docs, code and workflows, drives `git`/`gh`, and dispatches the subagents in [`.claude/agents/`](../.claude/agents/) |
| **Claude Code subagents** | `product-manager`, `software-engineer`, `qa-engineer`, `devops-sre` (see [agent-team.md](agent-team.md)) |
| **Claude Cowork** (claude.ai chat) | Planning: split the project into 4 prompts ([`prompts/00-PLAN.md`](../prompts/00-PLAN.md)), wrote the prompts, reviews the repo against the rubric after each prompt, guides the manual web steps |
| GitHub CLI (`gh`) | Issues, labels, milestones, Project board, PRs and checks, all driven by the agents |

## P0 — Prerequisites check (2026-11-10)

- **Prompt:** [`prompts/P0-prerequisites-check.md`](../prompts/P0-prerequisites-check.md)
- **AI did:** inspected git, gh (auth and scopes), Docker, Node, Python, uv, make and curl, and reported a status table without installing anything.
- **Human did:** started Docker Desktop, ran `gh auth refresh -s project,workflow` (browser step), created the empty public repo, and approved installing `make`.

## P1 — Foundation (2026-11-10)

- **Prompt:** [`prompts/P1-foundation.md`](../prompts/P1-foundation.md)
- **Summary:** turn the idea into a spec and a public tracker, define the agent team and context docs, and scaffold the backend, frontend and CI. No app features yet.

### What the tech lead session did
- Read the grading rubric first and mapped every criterion to planned evidence (README rubric table).
- Verified the Groq speech-to-text API against the current docs (endpoint, `whisper-large-v3-turbo`, 25 MB limit, parameters) before writing the spec.
- Wrote [`product-spec.md`](product-spec.md) (17 user stories with Given/When/Then ACs, NFRs, non-goals) and [`openapi.yaml`](../openapi.yaml).
- Created 12 labels, 4 milestones, **33 issues** (8 for M1 and the full backlog for M2–M4) with context, AC checklists, DoD and spec links, plus a public Project board.
- Wrote the agent definitions, `AGENTS.md`/`CLAUDE.md` and the modular docs.
- Committed docs directly to `main` (allowed for docs-only work) with `Refs #N`.

### What the agents did
- **software-engineer role (played by the tech lead session):** implemented issue #7 on branch `feat/7-skeleton-ci` and opened [PR #34](https://github.com/mrfmanuel/EchoNotes/pull/34) with `Closes #7`. The first CI run failed (`astral-sh/setup-uv@v10` has no floating major tag). It was fixed by pinning `v10.3.3`, and the next run was green.
- **`qa-engineer` subagent:** checked out the PR, ran the full backend and frontend suites (1 + 2 tests, lint, typecheck, build), started uvicorn and curled `/api/health`, checked secrets, `.env` tracking and CI caching, judged that oxlint instead of ESLint is acceptable, and posted an **APPROVED** [QA report](https://github.com/mrfmanuel/EchoNotes/pull/34#issuecomment-6770791245). The tech lead then squash-merged (`83ceab2`), and CI on `main` was green.
- **`product-manager` subagent:** groomed the first M2 issues (#9, #10, #11) against the spec, the architecture and `openapi.yaml`. It tightened the acceptance criteria (exact settings variables, slug rules, status/error codes, deterministic fake-provider output, Groq error mapping, test-isolation hooks), recorded dependencies, and commented *"Groomed — ready for software-engineer."* on each issue. It raised one product question (does adding content refresh a project's `updated_at`?), which the tech lead decided and recorded in [US-02 AC3](product-spec.md#us-02).
- All M1 issues were closed with evidence comments (files, commit SHAs, PR and QA links).
- **Caveat:** the subagent files were created during this session, so Claude Code had not registered them by name yet. The QA and PM runs were general-purpose subagents instructed to read and adopt their role file (see [agent-team.md](agent-team.md)).

### What a human verified
- Ran the P0 prerequisite fixes, approved the plan and wrote the prompt.
- **To do after P1:** review the spec and the tracker (Cowork review), check that the README renders, the [Project board](https://github.com/users/mrfmanuel/projects/2) is public and the CI badge is green.

## P2 — Build the app (2026-11-10)

- **Prompt:** [`prompts/P2-build-app.md`](../prompts/P2-build-app.md)
- **Summary:** the whole M2 milestone, from groomed backlog to a running, tested, containerized app, in one Claude Code session. The tech lead (main session) planned, dispatched and merged. All application code was written by the `software-engineer` and `devops-sre` subagents. Every PR was verified by an independent `qa-engineer` run that posted a QA report before the squash-merge.

### How the session was orchestrated
- From P2 on, the subagents were invoked **by name** (`product-manager`, `software-engineer`, `qa-engineer`, `devops-sre`), not as general-purpose stand-ins.
- The tech lead wrote one binding **technical brief** and passed it to every engineer, so agents that started cold made consistent decisions. It covered async SQLAlchemy with psycopg 3, the package layout, the version read only from `pyproject.toml`, error codes, the test setup on port 55432, and the frontend client via React context.
- Independent work ran **in parallel in isolated git worktrees**:
  - The frontend PRs ran while the backend chain was built.
  - Containerization ran beside the projects API.
  - Dependent backend PRs started from their predecessor's branch and rebased once it merged.
- Docs-only changes went straight to `main` with `Refs #N`, as [process.md](process.md) allows. These were the PM's grooming decisions, copied into the spec and contract (`fed907b`), and a contract note (`7ca56b2`).

### What each agent did

| Agent | Work |
|---|---|
| `product-manager` | Groomed all 16 open M2 issues, with comments on order, grouping and dependencies. Tightened ACs on 12 issues: error codes, the `.md` metadata line, slug rules, MiB units, and 422 for unknown transcript links. Created **#35** (JSON logs + `X-Request-ID`) and bug **#41** from QA findings. Listed 6 decisions that the tech lead copied into [product-spec.md §3.4.1](product-spec.md#341-conventions-decided-while-grooming-m2-2026-11-10) and `openapi.yaml` |
| `software-engineer` | 8 PRs: backend foundation, projects, transcription, transcripts, screenshots + export, test-suite completion, and two frontend PRs. Tests were written with the code (unit, Postgres integration and Vitest) |
| `devops-sre` | Multi-stage Dockerfile, `docker-compose.yml` and a CI Docker job (PR #40), and `scripts/smoke.sh` (PR #45) |
| `qa-engineer` | 13 QA runs: 10 PRs plus 3 re-checks after fixes. Each run checked out the PR, ran `make lint` and `make test`, verified every AC with tests **and** manual curl or Docker checks, and posted a criterion → evidence → result table on the PR |

### Pull requests (all squash-merged after green CI + QA APPROVED)

| PR | Issues | Content |
|---|---|---|
| [#36](https://github.com/mrfmanuel/EchoNotes/pull/36) | #17 #18 #19 | Frontend: typed API client, projects, upload/record with language hint, transcript editor (copy, download, unsaved-changes guard) |
| [#37](https://github.com/mrfmanuel/EchoNotes/pull/37) | #9 #16 #35 (refs #23) | Backend foundation: settings, async SQLAlchemy models, Alembic, DB health check, JSON logs, request IDs, Postgres test setup, Makefile, CI Postgres service |
| [#38](https://github.com/mrfmanuel/EchoNotes/pull/38) | #20 #21 | Frontend: screenshots (picker, Ctrl+V, link, gallery, dialog) and the Export ZIP button |
| [#39](https://github.com/mrfmanuel/EchoNotes/pull/39) | #10 | Projects CRUD API with unique slugs and the `updated_at` bump helper |
| [#40](https://github.com/mrfmanuel/EchoNotes/pull/40) | #22 | Dockerfile (SPA + API, non-root, migrations on start, HEALTHCHECK), compose with Postgres, CI image build and boot |
| [#42](https://github.com/mrfmanuel/EchoNotes/pull/42) | #11 #12 | `Transcriber` protocol, `fake` and `groq` providers, audio upload with 413/415/422/502/504 mapping |
| [#43](https://github.com/mrfmanuel/EchoNotes/pull/43) | #14 #15 | Screenshots API (magic bytes, 5 MiB), streamed ZIP export, shared `.md`/`.txt` renderers |
| [#44](https://github.com/mrfmanuel/EchoNotes/pull/44) | #13 | Transcript list, get, edit, download and delete; downloads proven byte-identical to the ZIP entries |
| [#45](https://github.com/mrfmanuel/EchoNotes/pull/45) | #24 | `scripts/smoke.sh` key-journey smoke test (Git Bash and Linux), run in CI against the compose stack |
| [#46](https://github.com/mrfmanuel/EchoNotes/pull/46) | #23 #41 | Full-flow, privacy and migration integration tests, contract test against `openapi.yaml`, one-command `make test`, flaky-test fix, Windows event-loop fix, log-format fixes |

**Final counts:** 387 backend unit tests, 38 backend integration tests (real Postgres), 129 frontend tests, and a 10-step smoke script. `make test` and CI on `main` are green.

### Problems found by QA and by the process
- **PR #38, changes requested.** Export ZIP was a plain link with no busy state and no error handling (#21 AC2). It was rebuilt as a button that fetches the ZIP as a blob, shows "Preparing…" and an error alert, and returns focus when the image dialog closes. QA then re-checked it.
- **PR #40, merged with "Refs #22" instead of "Closes #22".** QA approved the image, but the full journey could not run yet, so #22 stayed open. It was closed only after the smoke script passed through `docker compose`. The engineer also found and fixed a **stale-image bug**: uv's build cache shipped old app code.
- **Bug #41, found by QA on #37 and #39.** On native Windows, psycopg's async mode fails on the default Proactor event loop. The fix is a `--loop app.event_loop:new_event_loop` factory in the documented dev command. QA also found three logging and ordering problems, all fixed in #46:
  - uvicorn's `color_message` leaked into the JSON logs.
  - Alembic logged plain text instead of JSON.
  - Two endpoints returned screenshots in different orders.
- **Flaky frontend test.** It failed once during `make test` because of a race in the paste listener. The engineer reproduced it with parallel runs and fixed it; 12 out of 12 runs were then green.
- **Contract drift guard.** The new contract test forced `operation_id="getHealth"` so that FastAPI matches `openapi.yaml`.
- **Costs of running in parallel:**
  - The parallel branches caused 3 merge conflicts in `app/main.py`. Each was resolved with a merge commit and checked again before merging.
  - Two agents shared the compose project name `echonotes` and port 8000. One smoke run tore down another agent's stack.
  - One engineer killed a process by port number, which stopped Docker Desktop. Docker was restarted and nothing was lost.
  - A usage-limit interruption paused two agents. Both were resumed from their saved state.

### Tech-lead verification (step 6 of the prompt)
- **Fresh stack and smoke test:** after `docker compose down -v && docker compose up --build -d`, `scripts/smoke.sh http://localhost:8000` passed **10/10** steps with the fake provider.
- **Real Groq check:** the stack was restarted with `TRANSCRIBER_PROVIDER=groq`, reading the key from `.env` without printing it. A 9.5 s English speech clip made with Windows SAPI returned **201 in about 0.6 s**, with provider `groq`, language `en` and an accurate text. The only error was "Grok" for "Groq". The container logs contained no title, text or key.
- **Screenshots:** the README screenshots were captured with Playwright against the running stack ([docs/images/](images/)).

### What a human must still verify
- **Recording from a real microphone** (US-06) and the permission-denied message. These are only covered by unit tests with a mocked `MediaRecorder`.
- **Ctrl+V paste of a real screenshot** from the OS clipboard (US-13) in Chrome, Firefox and Edge.
- A **real Groq transcription in Spanish or Portuguese**, recorded in the browser.
- The downloaded `.md`/`.txt` files and the ZIP, opened in a real notes app or file manager.
- The layout on a real phone and in dark mode.

## P3 — Deploy and CI/CD (2026-11-10/11)

- **Prompt:** [`prompts/P3-deploy-cicd.md`](../prompts/P3-deploy-cicd.md)
- **Summary:** milestone M3, from groomed issues to live dev and prod with automatic CD to dev, gated promotion to prod, automatic and manual rollback, all proven with real runs. The human did the account work beforehand: a Neon project with `production` and `development` branches, two Render Docker services with auto-deploy off, and a git-ignored `.env.deploy`. The tech lead did the GitHub configuration with `gh`. Subagents wrote all code and workflows.

### How the session was orchestrated
- **Checked before building:**
  - **Configuration first, done by the tech lead:** it checked that `.env.deploy` is git-ignored, then loaded the two deploy-hook secrets and the `DEV_URL`/`PROD_URL` variables. Values were piped into `gh secret set` and never printed. It created the `development` and `production` environments (production with required reviewer `mrfmanuel`) and protected `main` with the three CI jobs as required checks, not enforced for admins.
  - **Platform facts checked against the docs:** a `web-fetch` agent read Render's documentation. It confirmed deploy hooks accept `ref=<sha>` (200 = started, 202 = busy, 404 = unknown SHA) and that `RENDER_GIT_COMMIT` is available at runtime. Both facts went into the engineers' briefs.
  - **Baseline:** before any change, `scripts/smoke.sh` passed against the already running dev service with the real Groq provider.
- **Parallel PRs in isolated worktrees:** the health/version PR (`software-engineer`) and the CD PR (`devops-sre`) were built at the same time. The CD PR depended only on the field names agreed in the groomed issue (`commit`, `environment`, `SMOKE_EXPECT_COMMIT`), and #47 merged first.
- **Live proof by the tech lead** after merging: the automatic dev deploy, the prod promotion with the human approving in GitHub, the dev rollback demo and redeploy, and a real Groq transcription on prod.

### What each agent did

| Agent | Work |
|---|---|
| `product-manager` | Tightened the ACs of #25–#28 to match the prompt. Created **#47** (commit and environment in `/api/health` and the UI footer) and **#48** (branch protection). Set the delivery order. Updated US-17 in the spec |
| `software-engineer` | PR #50: `commit`/`environment` in health (`RENDER_GIT_COMMIT` → `GIT_SHA` → `unknown`), `GIT_SHA` in the image, openapi + contract test, UI footer, `SMOKE_EXPECT_COMMIT`, `smoke-test-*` project names with cleanup checked on a forced failure |
| `devops-sre` | PR #49: `scripts/deploy.sh` (hook with `ref`, 202 backoff, health polling until the commit matches, smoke, job summary, hook URL kept off curl's arguments and masked) and `scripts/resolve-commit.sh`. The `deploy-dev`, `deploy-prod` and `rollback` workflows. Mock tests (27 cases), shellcheck and actionlint clean |
| `qa-engineer` | 3 runs: #49 APPROVED with follow-ups; #50 CHANGES REQUESTED, then APPROVED on re-check |
| `web-fetch` | Read the Render docs (deploy hooks, env vars, rollbacks) |

### Pull requests and issues

| PR | Issues | Content |
|---|---|---|
| [#50](https://github.com/mrfmanuel/EchoNotes/pull/50) | #47 | Deployed commit and environment in `/api/health` and the UI footer; smoke checks the commit |
| [#49](https://github.com/mrfmanuel/EchoNotes/pull/49) | #25 #26 #27 | CD: auto dev, gated prod with auto-rollback, rollback workflow, shared `deploy.sh` |
| docs commits on `main` | #48 #28 | Branch protection recorded in `process.md`; deployment, release process, README, AGENTS.md |

### Problems found by QA and by the process
- **#50, CHANGES REQUESTED:** `docker-compose.yml` set `GIT_SHA` at runtime, which replaced the commit baked into the image, so CI's health check reported `commit=unknown`. The fix left `GIT_SHA` as a build arg only and commented it out in `.env.example`, with a test to keep it that way. The smoke script's mismatch message now prints full SHAs.
- **#49 follow-ups applied before merge:**
  - Concurrency was set at workflow level, so a deploy-dev run created by a failed CI could replace a pending good deploy. It was moved to job level.
  - The `development` environment is now limited to protected branches, so only runs on `main` can use the dev hook.
- **Seen live:** merging #50 and #49 back to back cancelled the CI run for #50 on `main`. The deploy-dev run it created skipped its job as designed, and the next green CI deployed.
- **Rate limit:** a usage-limit interruption stopped the #47 engineer partway through; it was resumed from its saved state.
- **Decision recorded in AGENTS.md:** the post-deploy smoke test uses the deployed service's Groq provider with a 1 s silent clip, one call per deploy. CI test jobs still never call Groq, and CI never holds the key.

### Tech-lead verification (live)
- **Automatic dev deploy:** CI on `main` for `ebdef98`, then `deploy-dev` started on its own via `workflow_run`. The hook returned 200, health reported the commit after 61 s, and the smoke test passed.
- **Prod promotion:** `deploy-prod` waited in `production` until the human approved. Prod reported `ebdef98`/`prod` after 63 s and the smoke test passed (its project was deleted).
- **Rollback demo:** dev was rolled back to `875b2f8` (46 s, smoke passed), then redeployed to `ebdef98`.
- **Real Groq on prod:** a 9.5 s English clip returned 201 in 1.5 s with an accurate transcript, and the project was deleted (prod has 0 projects).
- **Secrets:** no hook key appears in any run log (`key=` occurs 0 times).
- **Run links:** [release-process.md](release-process.md#evidence-real-runs-2026-11-1011).

### What a human must still verify
- Open the live demo in a browser: check the footer shows `v0.1.0 · ebdef98 · prod`, and record a short clip with the microphone over HTTPS.
- Optionally try a Render dashboard rollback once to see it.

## P4 — Observability and on-call *(planned)*
