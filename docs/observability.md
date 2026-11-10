# Observability, Alerting and On-call

> Status: **planned in P4 (M4 Observability & On-call).** The privacy rules below already apply to all code.

## Plan

- **Instrumented journey:** *upload audio → transcript visible → export* (`POST /api/projects/{id}/transcriptions`, `GET /api/projects/{id}/export`).
- **Signals:** OpenTelemetry traces (FastAPI, SQLAlchemy, httpx to Groq), metrics (request rate, error rate, latency histograms, `transcriptions_total{provider,status}`, `transcription_duration_seconds`), and structured JSON logs with `trace_id` and `span_id` so all three correlate to a single request.
- **Backend for signals:** an OTLP exporter to a hosted backend (for example Grafana Cloud) with a UI for traces, metrics and logs. To be decided in P4.
- **Alert on user impact:** for example, *transcription failure rate > 20 % over 10 min* or *p95 transcription latency > 60 s*, never CPU. Each alert links to a runbook in `docs/runbooks/`.
- **On-call responder agent:** triggered by the alert (webhook → GitHub Actions `repository_dispatch`). It reads the runbook, gathers telemetry and recent deploys, opens an incident issue, and opens a fix or rollback PR that goes through the normal QA/CI gate.

<a id="privacy"></a>
## Telemetry privacy rules (apply now)

| Allowed in logs, spans and metrics | Never allowed |
|---|---|
| Resource IDs (UUIDs), sizes in bytes, durations, content types, HTTP status, provider name, language code, error class or code | Transcript text or titles, filenames typed by users, audio or image bytes, `GROQ_API_KEY`, `DATABASE_URL`, request bodies |
