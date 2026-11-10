#!/bin/sh
# Container entrypoint (#22): apply migrations, then start uvicorn on $PORT.
# Any other command (e.g. `docker run <img> id -u`) is executed as given.
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Fails (and so the container exits non-zero) when the database is unreachable or a migration
# breaks. Alembic logs revision IDs only, never the database URL.
alembic upgrade head

# Proxy headers are trusted from FORWARDED_ALLOW_IPS (set in the image; Render terminates TLS).
# Uvicorn's access log is off: RequestContextMiddleware writes one JSON access line without
# query strings.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --no-access-log
