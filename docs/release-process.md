# Release Process

> Status: **planned in P3 (M3 Deploy & CI/CD).**

## Intended flow

1. A PR is merged to `main` after CI is green and QA approves (see [process.md](process.md)).
2. CD builds the image tagged with the commit SHA and deploys it to **dev** automatically. A post-deploy smoke test, `scripts/smoke.sh <dev-url>` (see [testing.md](testing.md#end-to-end-smoke-test-scriptssmokesh-24)), runs the key journey and fails the deploy on any error.
3. The human (or `devops-sre`) checks dev, then runs the **Deploy to prod** workflow manually with the SHA to promote.
4. After the prod deploy, `scripts/smoke.sh <prod-url>` runs again (with `SMOKE_ALLOW_EMPTY_TEXT=1` on Groq); a failure means rollback.
5. The prod deploy is recorded (GitHub deployment and environment) with its SHA.

## Rollback (to be implemented in P3)

- **Fast path:** re-run the prod deploy workflow with the previous known-good SHA (or use Render's "rollback to previous deploy").
- Migrations must be backward compatible (expand → migrate → contract) so a rollback of the app does not require a DB rollback.
- Every rollback is logged as an incident issue with a timeline.
