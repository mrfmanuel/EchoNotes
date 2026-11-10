You are the tech lead (orchestrator) for EchoNotes. This is prompt 3 of 4: deployment and CI/CD (milestone "M3 Deploy & CI/CD"). Work autonomously through ALL steps below in this single session; do not stop to ask me questions unless you are truly blocked. Everything you write must be in English. Follow AGENTS.md, docs/process.md and docs/agent-team.md (issue → branch → PR → CI green → qa-engineer APPROVED → squash-merge → close issue with evidence). Use the `devops-sre` subagent for the infra work and `qa-engineer` for verification; `product-manager` grooms the M3 issues first (and creates any missing one, e.g. branch protection).

First commit: add `prompts/P3-deploy-cicd.md` (this prompt) in a docs commit.

## What already exists (set up manually by me)
- **Neon Postgres** project `echonotes` with two branches: `production` and `development` (separate databases).
- **Render** (free plan), two Docker web services built from this repo's root `Dockerfile`, branch `main`, health check path `/api/health`, **Auto-Deploy OFF**:
  - `echonotes-dev` → Neon `development` DB, `APP_ENV=dev`, `TRANSCRIBER_PROVIDER=groq`
  - `echonotes-prod` → Neon `production` DB, `APP_ENV=prod`, `TRANSCRIBER_PROVIDER=groq`
- A git-ignored local file `.env.deploy` with: `RENDER_DEV_DEPLOY_HOOK`, `RENDER_PROD_DEPLOY_HOOK`, `DEV_URL`, `PROD_URL` (and `RENDER_API_KEY` if present). NEVER print, echo or commit these values — read them only to pass them to `gh secret set` / `gh variable set`. Verify `.env.deploy` is git-ignored before doing anything.

## Rubric targets for this prompt
- **Deployment (2 pts):** the app is reachable at a public URL (prod), documented in the README.
- **CI/CD (3 pts):** CI runs tests on every PR; CD automatically deploys to **dev** after CI passes on `main`; **production is a manual deploy** (approval gate); there is a documented and tested **rollback path**.

## Tasks

1. **GitHub configuration (via `gh`):**
   - Repo secrets: `RENDER_DEV_DEPLOY_HOOK`, `RENDER_PROD_DEPLOY_HOOK` (and `RENDER_API_KEY` if provided), loaded from `.env.deploy` without echoing.
   - Repo variables: `DEV_URL`, `PROD_URL`.
   - GitHub Environments `development` and `production`; `production` requires a reviewer (me, `mrfmanuel`) before the job runs. If the API cannot add a required reviewer on this plan, fall back to `workflow_dispatch`-only + a typed confirmation input, and document it.
   - Branch protection on `main`: require the CI status checks to pass before merging PRs; do NOT enforce for admins (so docs commits can still go straight to main as docs/process.md allows). Record this in docs/process.md.

2. **Version visibility:** `/api/health` must also return the deployed git commit (`commit`: from Render's `RENDER_GIT_COMMIT` env var, or `GIT_SHA` build arg, falling back to `"unknown"`) and `environment` (`APP_ENV`). Update openapi.yaml, tests and the smoke script accordingly. Show the version + short commit in the UI footer.

3. **CD workflows (`.github/workflows/`):**
   - `deploy-dev.yml`: triggered by `workflow_run` of CI completing successfully on `main` (and `workflow_dispatch`). Calls the dev deploy hook for that exact commit (Render deploy hooks accept `?ref=<commit-sha>` for Git-backed services — verify in the current Render docs; if not supported, deploy the latest `main` and still verify the commit). Then poll `${DEV_URL}/api/health` until `commit` equals the CI commit SHA (generous timeout ~15 min: free instances build slowly and cold-start), then run `scripts/smoke.sh "$DEV_URL"`. Fail the workflow if verification or smoke fails. Write a job summary (commit, URL, result).
   - `deploy-prod.yml`: `workflow_dispatch` with input `ref` (commit SHA to promote; default = the commit currently running on dev, read from `${DEV_URL}/api/health`). Runs in the `production` environment (manual approval). Before deploying, record the currently running prod commit as `previous_commit` in the summary. Deploy that exact commit via the prod hook, poll prod health until the commit matches, run the smoke test (use a clearly-named smoke project and delete it at the end so prod data stays clean — make `smoke.sh` clean up after itself). If verification fails, automatically trigger a rollback to `previous_commit` and fail the run.
   - `rollback.yml`: `workflow_dispatch` with inputs `environment` (dev|prod) and `ref` (commit to roll back to); same deploy + verify + smoke logic. Factor the shared logic into a reusable workflow or a script (`scripts/deploy.sh`) to avoid duplication.
   - Keep CI as is (unit + integration + frontend + image build) and make sure the deploy workflows never run for PRs.

4. **Prove it works end to end (devops-sre + qa-engineer):**
   - Merge the M3 PRs; confirm `deploy-dev` ran automatically after CI and dev health shows the new commit.
   - Run `deploy-prod` (`gh workflow run deploy-prod.yml`). It will wait for my approval in the `production` environment: tell me clearly in the terminal "APPROVE NOW: <run URL>" and poll with `gh run watch` until I approve and it finishes.
   - Demonstrate the rollback path once: run `rollback.yml` for **dev** to the previous main commit, verify health shows that commit, then redeploy dev to the latest commit. Link these runs in docs/release-process.md as evidence.
   - Do one real transcription on prod with a short clip if you can generate one; otherwise verify `/api/health` + smoke and ask me to record a short clip in the prod UI.

5. **Docs:**
   - `docs/deployment.md`: architecture (GitHub → Actions → Render dev/prod → Neon dev/prod), environments table (URL, DB branch, provider, auto/manual), required secrets/variables (names only), first-time setup steps (what I did manually in Neon/Render), free-tier caveats (cold starts ~1 min, spin-down after 15 min idle), and DB migrations on deploy.
   - `docs/release-process.md`: the flow diagram (Mermaid) PR → CI → main → auto deploy dev → smoke → manual promote to prod (approval) → smoke → auto-rollback on failure; manual rollback options (rollback.yml, Render dashboard "Rollback"); evidence links to real runs.
   - README: prominent **Live demo** link (prod) + dev link, CI/CD badges, update the rubric table, note that the demo has no auth (do not upload sensitive audio).
   - Append the P3 section to `docs/ai-usage-report.md`. Close milestone "M3 Deploy & CI/CD".

When done, print a concise summary: prod and dev URLs, the run URLs for CI, deploy-dev, deploy-prod and the rollback demo, the health output of both environments, PRs/issues closed, and anything I must still do manually before prompt 4.
