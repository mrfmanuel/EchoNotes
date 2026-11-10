# syntax=docker/dockerfile:1
# EchoNotes: one image that serves the FastAPI API and the built React SPA (#22).
#   stage 1 frontend : node builds frontend/dist
#   stage 2 backend  : uv installs the backend (no dev deps) into /app/.venv
#   stage 3 runtime  : python slim + venv + alembic + static SPA, non-root, no Node, no uv
# Layers are ordered for caching: lockfiles first, sources last.

ARG NODE_IMAGE=node:24-slim
ARG PYTHON_IMAGE=python:3.12-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.9

# --- 1. Frontend build -------------------------------------------------------------------
FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Backend dependencies -------------------------------------------------------------
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS backend
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Third-party dependencies only: this layer is reused until uv.lock changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# The app itself, installed as a regular (non-editable) package so importlib.metadata works.
COPY backend/app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- 3. Runtime --------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PORT=8000 \
    STATIC_DIR=/app/static \
    FORWARDED_ALLOW_IPS="*"

RUN groupadd --system --gid 10001 echonotes \
    && useradd --system --uid 10001 --gid echonotes --home-dir /app --no-create-home \
       --shell /usr/sbin/nologin echonotes

WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY --from=frontend /src/frontend/dist ./static
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/docker-entrypoint
COPY --chmod=0644 docker/healthcheck.py /usr/local/bin/healthcheck.py

# Files stay root-owned (read-only for the app user); the app writes nothing to disk.
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/usr/local/bin/healthcheck.py"]

ENTRYPOINT ["docker-entrypoint"]

# Traceability: every image is labelled with the commit it was built from.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="echonotes" \
      org.opencontainers.image.source="https://github.com/mrfmanuel/EchoNotes" \
      org.opencontainers.image.revision="${GIT_SHA}"
