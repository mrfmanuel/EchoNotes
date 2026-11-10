# Observability, Alerting and On-call

> Status: **planned in P4 (M4 Observability & On-call).** The privacy rules below already apply to all code.

## Plan

- **Instrumented journey:** *upload audio → transcript visible → export* (`POST /api/projects/{id}/transcriptions`, `GET /api/projects/{id}/export`).
- **Signals:** OpenTelemetry traces (FastAPI, SQLAlchemy, httpx to Groq), metrics (request rate, error rate, latency histograms, `transcriptions_total{provider,status}`, `transcription_duration_seconds`), and structured JSON logs with `trace_id` and `span_id` so all three correlate to a single request.
- **Backend for signals:** an OTLP exporter to a hosted backend (for example Grafana Cloud) with a UI for traces, metrics and logs. To be decided in P4.
- **Alert on user impact:** for example, *transcription failure rate > 20 % over 10 min* or *p95 transcription latency > 60 s*, never CPU. Each alert links to a runbook in `docs/runbooks/`.
- **On-call responder agent:** triggered by the alert (webhook → GitHub Actions `repository_dispatch`). It reads the runbook, gathers telemetry and recent deploys, opens an incident issue, and opens a fix or rollback PR that goes through the normal QA/CI gate.

## Logging (M2)

Implemented in `backend/app/logging.py` and `backend/app/middleware.py` (#35).

- **Format:** one JSON object per line on stdout. Every record has `timestamp` (ISO-8601 UTC), `level`, `logger`, `message` and `request_id` (`null` outside a request). Extra fields passed with `extra=` are added as keys. Exceptions add `exc_type` (class name) and `stack_trace` (frames only; the exception message is dropped because it can echo user input).
- **Level:** `LOG_LEVEL` (`DEBUG|INFO|WARNING|ERROR|CRITICAL`, default `INFO`). Uvicorn's `uvicorn`/`uvicorn.error` loggers go through the same JSON handler; uvicorn's own access log is disabled. HTTP client loggers (`httpx2`, `httpcore2`) are limited to `WARNING` because they print full URLs.
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
