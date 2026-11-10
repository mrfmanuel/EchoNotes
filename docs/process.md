# Development Process

How work moves from an idea to `main`. The roles are described in [agent-team.md](agent-team.md).

## 1. Everything starts with a GitHub issue

- The tracker is public: <https://github.com/mrfmanuel/EchoNotes/issues>. The board is the **EchoNotes** GitHub Project.
- No code without an issue. If you find work while implementing, open a new issue instead of widening the PR.
- Milestones: `M1 Foundation`, `M2 App`, `M3 Deploy & CI/CD`, `M4 Observability & On-call`.

### Labels

| Group | Labels |
|---|---|
| Type (exactly one) | `type:feature`, `type:test`, `type:infra`, `type:docs`, `type:bug` |
| Area (one or more) | `area:backend`, `area:frontend`, `area:devops` |
| Owner agent | `agent:pm`, `agent:swe`, `agent:qa`, `agent:devops` |

<a id="issue-template"></a>
### Issue template

```markdown
## Context
Why this matters and what part of the system it touches.

## Acceptance criteria
- [ ] Given ..., when ..., then ...
- [ ] ...

## Definition of done
- [ ] Code + tests merged to `main` via PR with `Closes #N`
- [ ] CI green; QA report posted on the PR
- [ ] Docs / `openapi.yaml` updated if behavior or contract changed

## Spec
docs/product-spec.md#us-xx
```

## 2. Branches

- `main` is always releasable and protected by CI. From M3 on, it auto-deploys to dev.
- One branch per issue: `feat/<N>-<slug>`, `fix/<N>-<slug>`, `chore/<N>-<slug>`, `docs/<N>-<slug>` or `test/<N>-<slug>`.
- Short-lived branches. Rebase on `main` before opening the PR if it moved.
- **Exception:** docs-only changes may be committed directly to `main` by the tech lead, with `Refs #N` in the commit message.

## 3. Commits

[Conventional Commits](https://www.conventionalcommits.org/) with the issue reference:

```
feat(api): add project CRUD endpoints

Refs #12
```

Types: `feat`, `fix`, `test`, `docs`, `chore`, `ci`, `refactor`, `perf`. Use `Closes #N` in the PR body or in the final commit to close the issue on merge.

## 4. Pull requests

PR template (body):

```markdown
Closes #N

## What
Short summary of the change.

## How to verify
Commands / steps; test names that cover each acceptance criterion.

## Checklist
- [ ] Tests added/updated and passing locally
- [ ] No secrets, no transcript text in logs
- [ ] openapi.yaml / docs updated if needed
```

Merge gate (all required):
1. CI green (`gh pr checks <PR> --watch`)
2. QA report from `qa-engineer` with **APPROVED**
3. Squash-merge by the tech lead: `gh pr merge <PR> --squash --delete-branch`

## 5. Closing issues with evidence

- PR merges close issues automatically via `Closes #N`. The issue then links to the PR, the CI run and the QA report.
- Work done without a PR (docs on `main`) is closed with a comment: what was done, the files and the commit SHA.

## 6. Definition of done (global)

An issue is done when all of these hold:
- every acceptance criterion is checked and has evidence (test or QA note)
- tests are written with the code and the whole suite passes locally and in CI
- lint and type checks are clean (ruff, ESLint, `tsc`)
- docs, `openapi.yaml` and `.env.example` are updated when affected
- there are no secrets and no customer data in code, logs or telemetry
- it is merged to `main` and the issue is closed with evidence
