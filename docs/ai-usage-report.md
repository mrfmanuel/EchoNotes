# AI Usage Report

How AI tools were used to build EchoNotes, what the agents did, and what a human verified. This report is updated after each prompt (P1–P5). The prompts themselves are stored in [`prompts/`](../prompts/).

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

## P4 — Observability and on-call (2026-11-11)

- **Prompt:** [`prompts/P4-observability-oncall.md`](../prompts/P4-observability-oncall.md)
- **Summary:** milestone M4. It covers OpenTelemetry on the key journey, a local Grafana LGTM stack with a dashboard and a user-impact alert, and an alert-driven on-call responder that runs **headless Claude Code** under a policy enforced in code. The loop was demonstrated end to end, for real. Then came the final rubric audit, the docs, the release `v1.0.0` and the prod deploy.

### How the session was orchestrated
- **One binding brief before any code.** The tech lead wrote a P4 brief that every engineer received. It fixed the ownership of files per PR, the metric names *as seen in Prometheus*, span and attribute names, env vars, ports, datasource UIDs, the alert expression, the evidence API, the chaos-branch rule and the machine rules. Three `devops-sre` agents could then build in parallel in isolated worktrees: instrumentation (#29), stack + alert (#30/#31) and responder (#32).
- **Contract verified early, then broadcast.** The #29 engineer verified the metric and Loki label names against a real `grafana/otel-lgtm`. The tech lead forwarded them to the other two builds, including an alert edge case they found: with zero failures the numerator is empty, so the expression needs `or vector(0)`. The other PRs never had to be reworked for naming.
- **Live proof by the tech lead.** After merging, the tech lead ran `make incident` for real (twice, see below), captured the Grafana screenshots while the alert was firing, closed the responder's PR with a written reason and committed the incident folders.

### What each agent did

| Agent | Work |
|---|---|
| `product-manager` | Rewrote the ACs of #29–#33 to match the P4 design. Added US-18–US-21 and NFR-Observability to the spec. Ran the independent final rubric audit |
| `devops-sre` (×4 runs) | PR #51 (OpenTelemetry, redacting span processor, privacy tests), PR #53 (LGTM compose profile, provisioning, dashboard, alert, runbook), PR #52 (responder, evidence, policy, chaos patch, one-command demo, 80 tests), PR #55 (CLI schema fix after the first live run) |
| `qa-engineer` (×7 runs + final audit) | #51 APPROVED; #52 CHANGES REQUESTED → re-check → re-check 2 APPROVED; #53 CHANGES REQUESTED → APPROVED; #55 APPROVED (with a real `claude` call); independent final rubric audit |
| headless Claude Code (`claude -p`, opus) | **The on-call agent itself**, started by the alert: found the root cause from the evidence and wrote the fix + regression test in INC-20261111-052713 (16 turns, USD 0.47) |

### Pull requests and issues

| PR | Issues | Content |
|---|---|---|
| [#51](https://github.com/mrfmanuel/EchoNotes/pull/51) | #29 | Traces, metrics, logs with `trace_id`, optional OTLP export, privacy tests |
| [#53](https://github.com/mrfmanuel/EchoNotes/pull/53) | #30 #31 | `make obs-up`, Grafana LGTM, dashboard `echonotes-journey`, failure-ratio alert, webhook, runbook |
| [#52](https://github.com/mrfmanuel/EchoNotes/pull/52) | #32 | On-call responder, autonomy policy in code, `make incident` |
| [#55](https://github.com/mrfmanuel/EchoNotes/pull/55) | #32 | CLI-compatible `--json-schema` (found by the first live run) |
| [#56](https://github.com/mrfmanuel/EchoNotes/pull/56) | — | **Opened by the on-call agent**; closed without merging (the bug only existed on the chaos branch) |
| docs commits | #32 #33 | Incident evidence + screenshots, operations report, README review guide, rubric table, AGENTS.md |
| — | #54 | Availability alert, labelled `future` |

### Problems found by QA and by the process
- **QA found real security holes in the responder (#52).** QA reviewed the responder as an attack surface, not just as code:
  - **Git hooks:** code the agent writes runs under pytest. It could plant git hooks that commit a denied file or run with push credentials.
  - **Deleted tests:** the agent could delete a test that its fix breaks, and "tests pass" would still hold.
  - **Global git config:** a later re-check found that agent code could edit the operator's global git config (`pushInsteadOf`) and redirect the approved push.

  All were fixed with regression tests: hooks and config pinned, the commit built with `commit-tree` and compared with the evaluated diff, the push URL verified, `no_tests_removed`, secret scan, symlink and path checks, checks run in a clean checkout.
- **QA caught a fake recovery (#53).** The runbook's rebuild command turned telemetry off. The alert then went NoData → OK and looked "recovered". The fix added `make obs-rebuild-app`, and verification now requires `target_info` for the fixed commit.
- **Provider failures log at WARN**, so the first "error logs" panel was empty during a Groq outage. The panel and the evidence query now include WARN.
- **The first live run escalated (INC-20261111-051629).** The Claude Code CLI rejected the 2020-12 `$schema` in `--json-schema`. The policy did exactly its job: no answer meant escalation, and nothing was committed or pushed. The fix went through a normal PR (#55) with QA and a real call.
- **A merge closed #32 too early.** GitHub closed it from the PR description's `Closes #32`, so the tech lead reopened it until the demo evidence existed.
- **The usage limit stopped three agents and a QA run at once.** All four were resumed from their saved state.

### Tech-lead verification (live)
- **INC-20261111-052713 (`resolved_verified`):**
  - The alert fired at a 40 % failure ratio.
  - The evidence had 50 log lines with the stack trace, 3 traces and metrics.
  - Claude Code (opus) found `transcriptions.py:93` dividing by a 0.0 s duration. It fixed the guard and added a test that fails before the fix.
  - The policy approved and the responder opened PR #56. The app was rebuilt, then verified: 0/20 failures, the fixed SHA in telemetry, smoke passed, alert back to Normal.
  - **3 min 39 s from alert to verified recovery.** Full reconstruction: [operations-and-security-report.md](operations-and-security-report.md).
- **`make test`:** 713 tests pass (456 unit + 38 integration + 136 frontend + 83 responder). CI is green on `main`.

### What a human must still verify
- Look at Grafana yourself: `make obs-up`, then <http://localhost:3000>.
- Optionally rerun `make incident`. It costs a few tens of cents of model usage and needs `gh` and `claude` logged in.
- Approve the final prod deploy in GitHub's `production` environment.

## P5 — Bonus: AI-generated HTML project summary (2026-11-11/12)

- **Prompt:** [`prompts/P5-ai-summary.md`](../prompts/P5-ai-summary.md)
- **Summary:**
  - Milestone M5, story [US-22](product-spec.md#us-22).
  - A **Generate summary** button next to Export ZIP. It turns every transcript and screenshot of a project into one self-contained `summary.html`, made in the background by an LLM.
  - The summary has a title, an overview, key points, decisions and action items, one section per transcript, and the screenshots placed where they belong, each with a caption.
  - It is shown in a sandboxed iframe, can be downloaded, and is included in the ZIP.
  - Providers sit behind a pluggable `Summarizer`: `gemini` (default when `GEMINI_API_KEY` is set), `groq` (text only) and `fake` (tests and CI).
  - Released as app **v1.1.0**.

### How the session was orchestrated
- **Facts first, then a binding brief.** Before writing the P5 brief, the tech lead:
  - had a `web-fetch` agent read Google's model docs;
  - listed the models the real key can see. `gemini-3.8-flash` and `gemini-3.5-flash-lite` are both available, and no `temperature` may be sent to models from 3.6 on;
  - listed the Groq models, which gave the text fallback `openai/gpt-oss-120b`.

  The brief fixed the API contract, the config and its defaults, the HTML safety pipeline, the telemetry names and the machine rules.
- **The spec wins over the brief.** The PM numbered the story US-22, because US-18–21 were taken in P4. It chose some names (`error_code`, `no_transcripts`, `SUMMARY_MAX_CHARS`). The tech lead aligned the brief to the spec instead of the other way round.
- **Parallel build against a contract.** The backend (#58) and frontend (#59) were built at the same time in isolated worktrees. QA checked that the frontend's types matched the backend's `openapi.yaml` field by field. The ops PR for #60 was written against the backend PR's real variable and metric names before that PR merged.
- **Merge order on purpose.** The approved frontend PR waited for the backend, so dev never showed a button without an API. The ops PR merged last, because its dev smoke step calls the new endpoints.

### What each agent did

| Agent | Work |
|---|---|
| `web-fetch` | Read Google's Gemini model, rate-limit and pricing docs. Found that the free tier may use content to improve Google products |
| `product-manager` | US-22 (AC1–AC21) and NFR-AI-Summary, milestone M5, issues #58–#60; opened bug #64 from QA and real-run findings and updated AC19 |
| `software-engineer` (×3 builds + fixes) | PR #62 (backend: providers, prompt builder, nh3 sanitizer, background job, migration, ZIP, telemetry); PR #61 (frontend `SummaryPanel`); PR #65 (hardening: stale jobs, timeout/503 fallback, EXIF, conditional state writes) |
| `devops-sre` | PR #63: compose passthrough, Grafana summary panels, optional smoke step (on for dev deploys, with a provider check), docs, compose healthcheck fix |
| `qa-engineer` (×9 runs) | #61 CHANGES REQUESTED → APPROVED; #62 CHANGES REQUESTED → APPROVED; #63 CHANGES REQUESTED → APPROVED; #65 CHANGES REQUESTED → APPROVED. Every first review requested changes, and each one found something real |

### Pull requests and issues

| PR | Issues | Content |
|---|---|---|
| [#62](https://github.com/mrfmanuel/EchoNotes/pull/62) | #58 | Summarizer (gemini/groq/fake), `summaries` table + migration, 3 endpoints + contract, background job, sanitize-then-embed HTML, `summary.html` in ZIP, span + metrics + privacy tests |
| [#61](https://github.com/mrfmanuel/EchoNotes/pull/61) | #59 | Generate summary button, 3 s polling, sandboxed `srcdoc` iframe, download, error + retry, privacy note |
| [#63](https://github.com/mrfmanuel/EchoNotes/pull/63) | #60 | Compose vars, Grafana panels, `SMOKE_SUMMARY` step, docs, `pg_isready -h 127.0.0.1` |
| [#65](https://github.com/mrfmanuel/EchoNotes/pull/65) | #64 | Stuck-job recovery, fallback on primary timeout / transport error / 429 / 500 / 503, EXIF orientation, conditional writes |
| release PR | #60 | v1.1.0, README, this section |

### Problems found by QA, by real runs and by the process
- **The UI could lose a job it had just started (#61).** If the first `GET latest` was slow, it came back after a click on Generate and overwrote the new job. Polling stopped while the job ran unseen. QA reproduced it with a held-open request.
- **A 150 KiB screenshot could take down the 512 MB instance (#62).** A 6300×6300 PNG passed every upload check, and resizing it took the process from 45 to 560 MiB. QA measured it. The fix:
  - a 16 MP cap checked from the image header, before decoding;
  - no extra copy of the image in memory;
  - only one image decoded at a time.

  The worst case is now 194 MiB.
- **Other problems found by QA on #62:**
  - **Image size:** the tech lead turned a non-blocking finding into a requirement. Eight PNG screenshots could make `summary.html` 50–70 MB. Images are now JPEG, under a 4 MB budget.
  - **Crash on unusual digits:** a Unicode digit such as "²" in a screenshot number crashed the job (`isdigit` accepts it, `int` does not).
- **QA tried to break the sanitizer.** It ran 33 attacks against it (`<svg onload>`, mXSS variants, `javascript:` URLs, CSS `url()`, a transcript containing `</transcript>`, a hostile project name), and none got through. The output is also covered by a CSP that allows only `data:` images.
- **The first real Gemini run failed with 503 (`gemini-3.8-flash` overloaded).**
  - The app logged only the status code and no content.
  - Direct probes showed the model alternating between a fast 503 and hanging past 30 s, while `gemini-3.5-flash-lite` answered in about 1 s.
  - The first dev deploy then showed the hang for real: the summary step ended `provider_timeout` after 91 s, and the smoke test tolerated it as a warning.
  - **Fix (#64/#65):** the primary model gets its own 40 s timeout. A timeout, a transport error or a 429/500/503 triggers one fallback attempt within the overall 90 s deadline.
- **QA found a race in the first version of the stuck-job fix (#65).** A job marked stale but still alive could finish late, mark itself succeeded and delete the newer job. Every state change is now a conditional `UPDATE ... WHERE status IN ('pending','running')`, and image preparation counts toward the job deadline.
- **A rubric-level bug found by the real demo.** On a fresh volume, `docker compose up` could crash the app. The cause: `pg_isready` over the Unix socket passes while Postgres's temporary init server is running. The tech lead hit this on the real demo stack, and #63 fixed it with `-h 127.0.0.1`. CI had never shown it.
- **The usage limit stopped the hardening engineer in the middle of a fix.** It was resumed from its saved state after the reset.

### Tech-lead verification (live)
- **Local, real Gemini:** a demo project with 2 transcripts and 2 screenshots, generated through the real API and UI.
  - `gemini-3.8-flash` → 503, then the automatic fallback `gemini-3.5-flash-lite` → **succeeded in 12 s**: 2 transcripts, 2 images, about 104 KB of HTML.
  - The summary was accurate, with every required section. No `<script>`, no external URL, and both screenshots were embedded with fitting captions.
  - The download had `Content-Disposition: attachment; filename="summary.html"`, and the ZIP contained `summary.html`. Screenshots: [09](images/09-ai-summary.png), [10](images/10-ai-summary-figure.png).
- **Dev, real Gemini, run by the deploy smoke** ([run 43141655920](https://github.com/mrfmanuel/EchoNotes/actions/runs/43141655920)): `summary latest succeeded provider=gemini model=gemini-3.5-flash-lite` after 42 s. Download and ZIP passed.
- **`make test`:** **904 tests pass** (608 backend unit + 45 integration on Postgres + 168 frontend + 83 responder). CI is green on `main`.

### What a human must still verify
- Generate a summary on prod with your own (non-sensitive) audio and screenshots, and read it for accuracy and language. The model chooses the dominant language of the transcripts.
- Approve the prod deploy of v1.1.0.

### Retrospective addendum (P5)
- **Real calls beat documentation again.** The docs said `gemini-3.8-flash` was the stable free-tier Flash. In practice it was overloaded on every attempt that day. Only real runs, local and on dev, showed that the fallback path *was* the product. The original design only fell back on 429.
- **QA requested changes on every first review in P5, and each finding was real:** a UI race, an out-of-memory risk, a job crash, a docs error, and a race in the race fix. A skeptical independent verifier stayed the most valuable role.
- **Contract-first parallel work held up.** The frontend and backend were built at the same time against the brief, and they matched field for field on the first try.

## Retrospective (P0–P4)

**What worked**
- **Issue-first, with an independent QA agent.** Every PR had a QA report. QA requested changes on 4 PRs (#38, #50, #52, #53; #52 three rounds including a security follow-up) and each time found something real: missing error states, a commit hidden by compose, a git-hook bypass, a fake recovery. A separate verifier with a fresh context and a skeptical brief was the most valuable role on the team.
- **Binding briefs plus file ownership** let 3 engineers work in parallel without stepping on each other. The handful of merge conflicts were trivial.
- **Verifying against the real thing:**
  - real Postgres in the tests;
  - real `grafana/otel-lgtm` for metric names;
  - a real Render deploy with `ref=<sha>` and health-commit polling;
  - real `claude` calls to validate CLI flags;
  - a real end-to-end incident.

  Each of these caught something a mock would not have.
- **The policy-in-code design paid off on the very first live run.** When the agent produced nothing, the system escalated instead of guessing.

**What the agents got wrong**
- They assumed things about tools that were never checked: `--json-schema` accepting draft 2020-12, uv's build cache shipping stale code, compose overriding a baked env var, the Windows Proactor loop with psycopg. The fix each time was a real run, not more reasoning.
- They shared a machine carelessly early on (P2):
  - one smoke run tore down another agent's stack;
  - one agent killed a process by port and stopped Docker Desktop.

  From then on, private ports and project names per agent were part of every brief.
- They over-claimed in commit messages twice. One commit message described a change that hadn't applied, and a PR description went stale after a fix. QA flagged both.

**What humans verified or decided**
- The human set up the external accounts (Neon, Render, Groq, deploy hooks) and approved every production deploy in GitHub's `production` environment.
- The human was asked to check the app in a real browser (microphone, Ctrl+V, phone, dark mode) and to record Spanish/Portuguese audio on prod. These are the parts automated tests cannot prove.
- The human wrote and adjusted the prompts in [`prompts/`](../prompts/). The tech-lead session chose the trade-offs, for example: smoke on deployed envs uses the real provider, chaos PRs target a throwaway base branch, PR #56 closed without merging.
