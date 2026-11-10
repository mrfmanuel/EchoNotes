# Deployment

> Status: **planned in P3 (M3 Deploy & CI/CD).** Nothing is deployed yet.

## Target

| Environment | Where | Trigger | Database |
|---|---|---|---|
| local | `docker compose up --build` | manual | Postgres container |
| dev | Render web service `echonotes-dev` (Docker) | automatic on every merge to `main` | Render Postgres (or Neon) `echonotes-dev` |
| prod | Render web service `echonotes-prod` (Docker) | **manual** GitHub Actions workflow (`workflow_dispatch`) promoting a tested commit SHA | separate Postgres `echonotes-prod` |

- A single image serves the FastAPI API and the built React SPA.
- Configuration comes from env vars only (`DATABASE_URL`, `TRANSCRIBER_PROVIDER`, `GROQ_API_KEY`, …). See `.env.example`.
- Migrations (`alembic upgrade head`) run on container start before uvicorn.
- After each deploy, a health check (`GET /api/health`) gates success.

## To be documented in P3

- Render service and DB setup steps (including the manual steps for the human)
- GitHub secrets (`RENDER_API_KEY`, deploy hooks, service IDs)
- Public URLs for dev and prod
