# Observability, Alerting and On-call

> Status: **being built in P4 (M4 Observability & On-call).** The plan below follows the binding design in [`prompts/P4-observability-oncall.md`](../prompts/P4-observability-oncall.md). User stories: [US-18 … US-21](product-spec.md#us-18). The privacy rules below already apply to all code.

## Plan (M4)

| Piece | Issue | Story |
|---|---|---|
| OpenTelemetry traces, metrics and logs sharing `trace_id` | [#29](https://github.com/mrfmanuel/EchoNotes/issues/29) | [US-18](product-spec.md#us-18) |
| Local stack `observability/` (`grafana/otel-lgtm`) + dashboard | [#30](https://github.com/mrfmanuel/EchoNotes/issues/30) | [US-19](product-spec.md#us-19) |
| Alert on user impact + runbook | [#31](https://github.com/mrfmanuel/EchoNotes/issues/31) | [US-20](product-spec.md#us-20) |
| On-call responder (`incident-response/`) | [#32](https://github.com/mrfmanuel/EchoNotes/issues/32) | [US-21](product-spec.md#us-21) |

- **Instrumented journey:** *upload audio → transcript visible → export* (`POST /api/projects/{id}/transcriptions`, `GET /api/projects/{id}/export`).
- **Signals:** OTel traces (FastAPI, SQLAlchemy, a client span around the Groq call; `httpx2` has no official instrumentation, so the span may be manual), metrics (`echonotes_transcriptions_total{provider,status}`, `echonotes_transcription_duration_seconds`, `echonotes_exports_total{status}`, HTTP server metrics) and JSON logs with `trace_id`/`span_id` next to `request_id`, also exported via OTLP. Service `echonotes-api`.
- **Optional by design:** with `OTEL_EXPORTER_OTLP_ENDPOINT` empty, nothing is exported (tests, CI and Render prod run without a collector). A hosted prod backend (for example Grafana Cloud OTLP) is future work.
- **Backend for signals:** local single container `grafana/otel-lgtm` (Collector + Prometheus + Loki + Tempo + Grafana), started with `make obs-up`, provisioned from `observability/`.
- **Alert on user impact:** transcription failure ratio > 20 % over 2–5 min with a minimum request count, never CPU. Runbook: `docs/runbooks/transcription-failures.md`. Contact point: webhook to the host responder `http://host.docker.internal:9095/alert`.
- **On-call responder:** `incident-response/responder.py` on the host receives the webhook, collects read-only evidence, runs Claude Code headless in an isolated worktree, enforces `autonomy-policy.yaml` in code, then opens a PR and verifies recovery, or escalates. The demo (`test-incident.sh`) injects a bug on a throwaway branch `chaos/INC-<id>` that never reaches `main`.

## Logging (M2)

Implemented in `backend/app/logging.py` and `backend/app/middleware.py` (#35).

- **Format:** one JSON object per line on stdout. Every record has `timestamp` (ISO-8601 UTC), `level`, `logger`, `message` and `request_id` (`null` outside a request). Extra fields passed with `extra=` are added as keys. Exceptions add `exc_type` (class name) and `stack_trace` (frames only; the exception message is dropped because it can echo user input).
- **Level:** `LOG_LEVEL` (`DEBUG|INFO|WARNING|ERROR|CRITICAL`, default `INFO`). Uvicorn's `uvicorn`/`uvicorn.error` loggers go through the same JSON handler; uvicorn's own access log is disabled. HTTP client loggers (`httpx2`, `httpcore2`) are limited to `WARNING` because they print full URLs.
- **Uvicorn `color_message`:** uvicorn attaches a `color_message` extra (the message with ANSI color codes). The JSON formatter drops it, so no line contains `color_message` or `\x1b[` escapes (#41).
- **Migrations:** `alembic upgrade head` (run by the container entrypoint before uvicorn) configures the same JSON handler in `alembic/env.py`, so lines such as `Context impl PostgresqlImpl.` and `Running upgrade  -> 0001, ...` are JSON too. `alembic.ini` has no logging sections. The database URL is never logged (#41).
- **Known dev-only exception:** with `uvicorn --reload`, the reloader *parent* process (it watches files and restarts the worker) prints a few plain-text lines such as `Will watch for changes in these directories` and `Started reloader process`. It never imports the app, so our JSON handler is not installed there. The worker process that serves requests logs JSON. Production and Docker never use `--reload`.
- **Windows event loop:** on native Windows start uvicorn with `--loop app.event_loop:new_event_loop` (selector loop; psycopg's async mode cannot use the Proactor loop). If the app starts on a Proactor loop anyway, it logs one `ERROR` line at startup with the fix (#41).
- **`X-Request-ID`:** an incoming header matching `^[A-Za-z0-9._-]{1,128}$` is echoed; otherwise a new UUID4 is generated. The header is on every response, including 404, 422 and 500 (unhandled exceptions return `{"detail": "Internal Server Error"}`). The ID lives in a `contextvars.ContextVar`, so it is correct under concurrent requests. In M4 it will sit next to `trace_id`/`span_id`.
- **Access log:** exactly one line per request from logger `app.access` with `method`, `route` (the route template such as `/api/projects/{project_id}`, or the path without query string when no route matched), `status`, `duration_ms` and `request_id`.
- **Never logged:** query strings, request/response bodies, headers other than `X-Request-ID`, filenames, project names, transcript titles or text, image/audio bytes, `GROQ_API_KEY`, `DATABASE_URL`. The health check logs only the error class when the database is unreachable.

Example access line:

```json
{"timestamp": "2026-11-10T15:45:34.620904+00:00", "level": "INFO", "logger": "app.access", "message": "request completed", "request_id": "abc-123", "method": "GET", "route": "/api/health", "status": 200, "duration_ms": 3.12}
```

<a id="privacy"></a>
## Telemetry privacy rules (apply now)

| Allowed in logs, spans and metrics | Never allowed |
|---|---|
| Resource IDs (UUIDs), sizes in bytes, durations, content types, HTTP status, provider name, language code, error class or code | Transcript text or titles, filenames typed by users, audio or image bytes, `GROQ_API_KEY`, `DATABASE_URL`, request bodies |
