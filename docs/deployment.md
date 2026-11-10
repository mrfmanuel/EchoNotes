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

## Local: docker compose (M2, #22)

```bash
docker compose up --build        # or: make up   -> http://localhost:8000
docker compose down              # stop, keep the database volume
docker compose down -v           # stop and wipe the database
```

- **No `.env` needed.** `docker-compose.yml` has safe defaults: `TRANSCRIBER_PROVIDER=fake`, Postgres user/password/db `echonotes`, and `DATABASE_URL` pointing at the `db` service. `.env` is loaded if it exists (`env_file` with `required: false`), e.g. to set `TRANSCRIBER_PROVIDER=groq` and `GROQ_API_KEY`.
- Values in the compose `environment:` block win over `.env`, so the host-oriented `DATABASE_URL=...@localhost:5432/...` and the empty `STATIC_DIR=` from `.env.example` do not affect the container.
- Services: `db` = `postgres:16` with the named volume `pgdata` and a `pg_isready` healthcheck (no host port). `app` = the root `Dockerfile`, starts after `db` is healthy, published on `8000:8000`.

## The image (`Dockerfile`)

| Stage | Base | Does |
|---|---|---|
| `frontend` | `node:24-slim` | `npm ci && npm run build` → `frontend/dist` |
| `backend` | `python:3.12-slim` + `uv` (pinned `ghcr.io/astral-sh/uv` tag) | `uv sync --frozen --no-dev` into `/app/.venv` (lockfile layer first for caching) |
| `runtime` | `python:3.12-slim` | venv + `alembic/` + SPA in `/app/static`; no Node, no uv, no dev deps, no `.env` |

- **Port:** uvicorn listens on `$PORT` (default `8000`). Render injects `PORT`; `docker run -e PORT=9000 -p 9000:9000 ...` also works.
- **Migrations on start:** `docker/entrypoint.sh` runs `alembic upgrade head` and then `exec uvicorn`. If the database is unreachable or a migration fails, the container exits non-zero (the deploy fails instead of serving a broken schema). Passing a command (`docker run <img> id -u`) runs that command instead.
- **Non-root:** runs as `echonotes` (uid 10001); app files are root-owned and read-only.
- **Health:** `HEALTHCHECK` runs `docker/healthcheck.py` (stdlib `urllib`, no curl) against `GET /api/health`; the container is `healthy` only on 200 (database reachable).
- **SPA:** `STATIC_DIR=/app/static` makes FastAPI serve `/assets/*` and fall back to `index.html` for any other non-`/api` GET (client routes like `/projects/<id>`). Unknown `/api/*` paths stay JSON 404. Without `STATIC_DIR` (dev, tests) the app serves the API only.
- **Proxy:** uvicorn trusts `X-Forwarded-*` (`--proxy-headers`, `FORWARDED_ALLOW_IPS=*`) because Render terminates TLS in front of the container.
- **Traceability:** the `GIT_SHA` build arg sets the `org.opencontainers.image.revision` label (CI passes `github.sha`).
- **CI:** the `docker` job in `ci.yml` builds the image on every PR (Buildx, GitHub Actions layer cache, no push), checks it is non-root, boots it with compose and smoke-tests `/api/health`, `/`, a client route and an unknown `/api` path.

## To be documented in P3

- Render service and DB setup steps (including the manual steps for the human)
- GitHub secrets (`RENDER_API_KEY`, deploy hooks, service IDs)
- Public URLs for dev and prod
