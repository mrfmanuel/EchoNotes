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

## P2 — Build the app *(planned)*
## P3 — Deploy and CI/CD *(planned)*
## P4 — Observability and on-call *(planned)*
