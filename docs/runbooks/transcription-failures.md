# Runbook: EchoNotes transcription failure ratio high

| | |
|---|---|
| **Alert** | `EchoNotes transcription failure ratio high` (rule uid `echonotes-transcription-failure-ratio`, [`observability/alerts.yaml`](../../observability/alerts.yaml)) |
| **Severity** | `severity=page`, `journey=transcription` |
| **Fires when** | more than **20 %** of transcription requests failed over the last **2 min**, with at least **5** requests in that window, for **30 s** |
| **Failed means** | `status` = `provider_error` (HTTP 502), `timeout` (504) or `server_error` (500, unhandled exception). `client_error` (4xx: bad file, too large, unknown project) does not count |
| **Dashboard** | [EchoNotes key journey](http://localhost:3000/d/echonotes-journey) (uid `echonotes-journey`; use your `GRAFANA_PORT`), login `admin/admin` |
| **Automatic responder** | [on-call.md](../on-call.md): the agent gets this alert first and follows the same evidence. This runbook is the human procedure and the escalation path |
| **More context** | [observability.md](../observability.md) (signals, queries, evidence API), [release-process.md](../release-process.md#rollback) (rollback) |

## User impact

Users upload or record audio and get an error instead of a transcript. The key journey (*upload audio → transcript → export*) breaks at its first step. Export and editing of existing transcripts may still work. Audio is never stored, so a failed upload is lost and the user must retry.

## Symptoms

- The UI shows a "transcription failed" error after an upload or recording.
- The API returns **500**, **502** or **504** on `POST /api/projects/{id}/transcriptions`.
- On the dashboard, *Transcription failure ratio* is above the red 20 % line and *Transcriptions by status* shows `provider_error`, `timeout` or `server_error`.
- *Recent failure logs* shows lines from `echonotes-api`:
  - `WARN` for provider failures and timeouts (502/504): `transcription failed`, `transcription timed out`.
  - `ERROR` for unhandled exceptions (500), with `exc_type` and `stack_trace`.
  - The panel query is `{service_name="echonotes-api"} | severity_text=~"WARN|ERROR|FATAL"`. An `ERROR`-only filter misses every Groq incident.

## 1. Confirm and size it (2 min)

Open the dashboard from the alert (`dashboard_url` / `panelURL` in the notification).

| Check | Panel or query |
|---|---|
| Is it still happening? | *Transcription failure ratio (2 m window)* and the alert state (Grafana → Alerting) |
| How many users and requests? | *Transcriptions (5 m)*, the *requests in window* line |
| Which failure? | *Transcriptions by status*, or Prometheus: `sum by (status, provider) (increase(echonotes_transcriptions_total[5m]))` |
| Only transcription, or everything? | *HTTP 5xx ratio*. If all endpoints fail, suspect the database or the whole app (`/api/health`) |
| Latency too? | *Transcription latency p50 / p95*. A p95 near `TRANSCRIBE_TIMEOUT_SECONDS` (120 s) points to timeouts |

The same numbers from a terminal (evidence API, read-only):

```bash
G=http://localhost:3000   # GRAFANA_URL
curl -s -u admin:admin -G $G/api/datasources/proxy/uid/prometheus/api/v1/query \
  --data-urlencode 'query=sum by (status) (increase(echonotes_transcriptions_total[5m]))'
curl -s http://localhost:8000/api/health    # deployed commit + environment
```

## 2. Find the cause by status

### `server_error` (500): a bug in our code

Most likely after a deploy. The fake provider can produce it too, because it is our code, not Groq.

1. **Logs:** *Recent failure logs* or Explore → Loki:
   `{service_name="echonotes-api"} | severity_text="ERROR" | exc_type!=""`.
   Read `exc_type` and the stack frames (`stack_trace` on the stdout line; in Loki the record links to its trace). The last frame in `app/` is usually the faulty line.
2. **Trace:** expand the log line → *Open trace in Tempo* (or panel *Failing traces*). Check which span failed (`transcription.create`, the DB span, `groq.transcribe`) and its `error.type`.
3. **What changed:** compare the `commit` from `/api/health` with the last known-good commit:
   `git log --oneline <good>..<deployed> -- backend/` and `gh run list --workflow deploy-dev.yml --limit 5`.
4. **Does it hit every request or only some?** A partial ratio (for example 30 %) means a data- or input-dependent path, such as a language, a file type or a size.

### `provider_error` (502): Groq answered with an error or could not be reached

1. Loki: `{service_name="echonotes-api"} | severity_text="WARN"`. Provider failures log at `WARN` (`transcription failed` with `status_code`, `transcription timed out`), not at `ERROR`. Open a failing trace and check the upstream HTTP status on the `groq.transcribe` client span (`http.response.status_code`):
   - **401/403:** the `GROQ_API_KEY` is invalid or was revoked. Rotate it in the Render service env vars, which restarts the service. Never paste the key into an issue or a log.
   - **429:** rate limit or quota. Wait, or reduce traffic. It clears by itself.
   - **5xx or connection errors:** a Groq outage. Check the Groq status page and wait; there is nothing to roll back.
2. If only one provider fails, *Transcriptions by status* shows it per `provider`.

### `timeout` (504): Groq is too slow

1. *Transcription latency p95* near 120 s, with traces where `groq.transcribe` takes the whole time.
2. Usually a Groq slowdown, or very long files. Temporary mitigation: raise `TRANSCRIBE_TIMEOUT_SECONDS` in the Render env (bounded by Render's request timeout). Otherwise wait.

## 3. Mitigate

| Cause | Mitigation |
|---|---|
| Bad deploy (`server_error` started with a new commit) | **Roll back** to the last good commit: `gh run list --workflow deploy-prod.yml` to find it, then `gh workflow run rollback.yml -f environment=prod -f ref=<known-good-sha>` (prod waits for the reviewer's approval) or `-f environment=dev`. Follow it with `gh run watch`. The workflow verifies `/api/health` `commit` and runs the smoke test. Details: [release-process.md](../release-process.md#rollback) |
| Bug that rollback cannot fix (old data, input-dependent) | Fix forward: issue → branch → PR with a regression test → CI → QA → merge → `deploy-prod.yml`. The on-call agent may have opened a fix PR already ([on-call.md](../on-call.md)); review it like any PR |
| Invalid Groq key | Rotate `GROQ_API_KEY` in the Render env vars (dashboard → service → Environment) |
| Groq outage, rate limit or slowness | Wait and watch; tell users that transcription is degraded. Do **not** switch prod to `TRANSCRIBER_PROVIDER=fake`: it would return fake transcripts |
| Local demo stack | Rebuild only the app from the fixed commit **with telemetry kept on**: `make obs-rebuild-app`, which runs `OBS_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up --build -d --wait app`. Use the same `COMPOSE_PROJECT_NAME`, `APP_PORT`, `GRAFANA_PORT` and `APP_IMAGE`. ⚠️ A plain `docker compose up --build app` recreates the app with an empty `OTEL_EXPORTER_OTLP_ENDPOINT`. The app then exports nothing, the rule gets no data, `noDataState: OK` turns it Normal, and that **looks like a recovery but proves nothing** |

## 4. Verify recovery

"Normal" alone is not proof. The rule is also Normal when no data arrives (fewer than 5 requests, or an app that stopped exporting). Check that **fresh, successful samples arrive from the fixed app**:

1. `/api/health` shows the expected `commit`.
2. Drive traffic: run `scripts/smoke.sh <url>` **10 times** within 2 min (one transcription each). On prod it creates and deletes a `smoke-test-*` project. A freshly rebuilt app starts new counter series, and what it counts before its first export is not seen by `increase()`. Measured: 6 runs right after a rebuild counted as about 4.5, below the minimum of 5. 10 runs counted as about 8.4.
3. Local stack: the new app is exporting. Both queries must return a **non-empty** result:
   - `target_info{job="echonotes-api", vcs_ref_head_revision="<expected full sha>"}`: the fixed commit reports.
   - `sum(increase(echonotes_transcriptions_total{status="success"}[2m])) > 0`: new successful transcriptions arrive.
4. With **at least 5** transcriptions in the window (`sum(increase(echonotes_transcriptions_total[2m])) >= 5`, non-empty), the failure ratio query from section 1 is below `0.2`.
5. The alert goes back to **Normal**, and the contact point receives a `resolved` notification. It can resolve before the ratio is below 20 % if traffic drops under 5 requests (see [design limits](../observability.md#alert-design-limits)), so steps 3 and 4 are the real check.

## 5. Escalate

Escalate to the human owner (`mrfmanuel`, the `production` reviewer) by opening a GitHub issue titled `INCIDENT: <short symptom>` with labels `type:bug` and `area:devops`, assigned to `mrfmanuel`, when **any** of these is true:

- The alert is still firing **15 min** after the first mitigation, or the failure ratio is above 50 %.
- The fix needs a prod deploy or rollback. Prod always waits for the reviewer's approval, so ask for it with the run URL.
- The on-call agent wrote `escalation.md` (its fix failed the autonomy policy: paths, size, tests or schema) or its confidence is low. See [on-call.md](../on-call.md).
- The cause is outside the code: Groq account, key or quota, Render or Neon outage, or anything that needs credentials the responder does not have.
- Data loss or a privacy problem is possible (for example user content in logs). In that case stop and escalate first; do not keep collecting evidence.

Put in the issue: alert start time, measured ratio, the failing `status`, the deployed `commit`, one `trace_id`, what you tried and what happened. Never transcript text, filenames or keys.

## 6. Follow up

- Open or update an incident issue: timeline (alert start, mitigation, resolved), deployed and rolled-back commits, the evidence links (dashboard, a trace ID, the run URLs). No transcript text, filenames or keys.
- Add a regression test for the bug, and link the fix PR.
- If the alert was noisy or late, tune `observability/alerts.yaml` in a PR (window, threshold, minimum count).

## Note: where this alert runs

The alert, the dashboard and the telemetry run on the **local stack** (`make obs-up`). Render dev/prod do not export telemetry yet (future work in [observability.md](../observability.md#production-telemetry-future-work)). For a prod incident without telemetry, use the same steps with the Render service logs (JSON lines with `request_id`, `exc_type`, `stack_trace`), `/api/health` and `scripts/smoke.sh`.
