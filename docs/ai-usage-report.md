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
- The skeleton (issue #7) followed the full workflow: branch `feat/7-skeleton-ci` → PR with `Closes #7` → CI → **`qa-engineer` subagent** independently verified the PR against the acceptance criteria and posted a QA report → squash-merge. Links are added below when the PR exists.
- M1 issues were closed with evidence comments (files and commit SHAs).

### What a human verified
- Approved the plan and the prompt. Checks the spec and the tracker after P1 (a Cowork review).
- *To confirm by the human after P1:* the README renders correctly, the Project board is public, and CI is green.

## P2 — Build the app *(planned)*
## P3 — Deploy and CI/CD *(planned)*
## P4 — Observability and on-call *(planned)*
