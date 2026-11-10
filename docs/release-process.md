# Release Process

> Status: **planned in P3 (M3 Deploy & CI/CD).**

## Intended flow

1. A PR is merged to `main` after CI is green and QA approves (see [process.md](process.md)).
2. CD builds the image tagged with the commit SHA and deploys it to **dev** automatically. A post-deploy smoke test, `scripts/smoke.sh <dev-url>` (see [testing.md](testing.md#end-to-end-smoke-test-scriptssmokesh-24)), runs the key journey and fails the deploy on any error.
3. The human (or `devops-sre`) checks dev, then runs the **Deploy to prod** workflow manually with the SHA to promote.
4. After the prod deploy, `scripts/smoke.sh <prod-url>` runs again (with `SMOKE_ALLOW_EMPTY_TEXT=1` on Groq); a failure means rollback.
5. The prod deploy is recorded (GitHub deployment and environment) with its SHA.

## Workflows (#25, #26, #27)

```bash
# dev: automatic after CI on main (deploy-dev.yml); manual redeploy:
gh workflow run deploy-dev.yml [-f ref=<sha>]
# prod: manual promotion, waits for the `production` reviewer, auto-rollback on failure
gh workflow run deploy-prod.yml [-f ref=<sha>]       # empty ref = the commit running on dev
# rollback (same script, same gate for prod)
gh workflow run rollback.yml -f environment=prod -f ref=<known-good-sha>
gh run watch
```

All of them use `scripts/deploy.sh` (see [deployment.md](deployment.md#cd-workflows-and-scriptsdeploysh-25-26-27)). Every run's job summary shows the target SHA, the commit running before and the result, so each deploy is traceable to a commit.

- **Environments:** `production` requires reviewer `mrfmanuel` and is limited to protected branches. `development` is also limited to protected branches (no reviewer), so only workflow runs on `main` can use the dev deploy hook.
- **Concurrency:** dev uses the job-level group `deploy-dev` (in `deploy-dev.yml` and in the dev rollback job), so runs whose deploy job is skipped (CI failed or cancelled) never join the group and never displace a pending good deploy. Prod uses `deploy-prod`, set at workflow level in `deploy-prod.yml` and at job level in `rollback.yml`. Groups are repository-wide, so a deploy and a rollback of the same environment never overlap.
- **Render hook `202`** ("another deploy in progress", retried with backoff up to `DEPLOY_HOOK_WAIT`) is based on Render's documented behavior and has only been tested against the local mock so far. It will be confirmed on the first live run.

## Rollback

- **Automatic (prod):** if `deploy-prod.yml` fails at the hook, verification or smoke, it redeploys `previous_commit` with the same script and the run still ends failed. If `previous_commit` is `unknown` (e.g. prod still runs code from before `commit` was added to `/api/health`), there is no automatic rollback and the summary says so.
- **Manual:** `rollback.yml` (`environment` dev|prod, `ref` = a commit on `main` that reports `commit` in `/api/health`), or Render dashboard → service → Events → "Rollback" (does not update GitHub; record it in the incident issue).
- **Fast path:** re-run the prod deploy workflow with the previous known-good SHA (or use Render's "rollback to previous deploy").
- Migrations must be backward compatible (expand → migrate → contract) so a rollback of the app does not require a DB rollback.
- Every rollback is logged as an incident issue with a timeline.
