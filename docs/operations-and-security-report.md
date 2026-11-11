# Operations and Security Report

> This is the module 4 deliverable ("the model may reason; the system must observe, authorize, verify, and remember"). From one incident ID, a reader can reconstruct what was deployed, the user impact, the alert and the evidence, the model and how it was configured, the policy decision and the commands executed, and how recovery was verified. Everything below is linked to files committed in [`incident-response/incidents/`](../incident-response/incidents/).

| Incident | Short name | Outcome |
|---|---|---|
| [`INC-20261111-052713`](../incident-response/incidents/INC-20261111-052713/) | **INC-001** | Fixed by the agent, approved by the policy, PR [#56](https://github.com/mrfmanuel/EchoNotes/pull/56) opened, local stack rebuilt, recovery verified (`resolved_verified`) |
| [`INC-20261111-051629`](../incident-response/incidents/INC-20261111-051629/) | INC-000 (first attempt) | **Escalated.** The agent CLI failed before reasoning, the policy refused to act, and nothing was committed, pushed or deployed |

Both runs come from one command, `make incident` ([`incident-response/test-incident.sh`](../incident-response/test-incident.sh)), against a local incident stack: compose project `echonotes-incident`, app on :8001, Grafana on :3001. The stack runs a deliberately injected bug. The bug lives only on the throwaway branch `chaos/INC-<id>` and never reached `main`.

## INC-001 (`INC-20261111-052713`)

### 1. Deployed version and user impact
- **Deployed:** EchoNotes `0.1.0` at commit `c65a326`, reported by `/api/health` and by the Prometheus `target_info{vcs_ref_head_revision}` series. This commit is `main` (`4eaec6d`) plus the chaos commit *"perf(transcription): log the real-time factor of each transcription"*, applied from [`chaos/realtime-factor-zero-division.patch`](../incident-response/chaos/realtime-factor-zero-division.patch).
- **The bug:** the real-time-factor log line divides by the duration the provider reports. Very short clips report `0.0 s`, so they raised `ZeroDivisionError` and the request returned **HTTP 500**. Existing unit tests did not catch it, which is how a real regression escapes.
- **User impact:** **40 % of transcription uploads failed.** `echonotes_transcriptions_total{status="server_error"}` was about 73 against about 110 `success` in 5 minutes, and the failure ratio over 2 minutes was 0.40 ([`report.md`](../incident-response/incidents/INC-20261111-052713/report.md)). Every short upload failed. Normal uploads still worked.

### 2. Alert and evidence inspected
- **Alert:** *EchoNotes transcription failure ratio high* ([`observability/alerts.yaml`](../observability/alerts.yaml)). It fires when failed transcriptions (`provider_error|timeout|server_error`) are more than 20 % of all transcriptions over 2 minutes, with at least 5 requests. Labels: `severity=page`, `journey=transcription`. Annotations: summary, runbook, dashboard. It is a **user-impact** alert, not a CPU alert. It fired at 05:29:10Z and the Grafana webhook reached the responder ([`alert.json`](../incident-response/incidents/INC-20261111-052713/alert.json)).
- **Evidence packet** ([`evidence.json`](../incident-response/incidents/INC-20261111-052713/evidence.json)): collected by [`collect_evidence.py`](../incident-response/collect_evidence.py) **before** any model ran. All queries are read-only, allowlisted and bounded (GET only, 10 s timeout, 2 MB cap), sent through Grafana's datasource proxy. There were no collection errors. The packet contains:
  - **Health:** the `/api/health` response, which gives the deployed commit.
  - **Metrics:** Prometheus failure ratio and transcriptions by status.
  - **Logs:** 50 Loki failure log lines (`WARN|ERROR|FATAL`), each with `trace_id`, `exc_type=ZeroDivisionError` and the stack trace ending at `app/services/transcriptions.py:93`.
  - **Traces:** 3 failing Tempo traces. Each shows `transcription.create` with `error.type=ZeroDivisionError` and `echonotes.audio.size_bytes=44`.
  - **Git:** the 10 most recent commits.
- **Human view of the same signals:** [dashboard during the incident](images/05-grafana-dashboard-incident.png), [firing alert](images/06-grafana-alert-firing.png), [trace with its correlated logs](images/07-grafana-trace-and-logs.png).

### 3. Model and configuration
Recorded in [`agent-config.json`](../incident-response/incidents/INC-20261111-052713/agent-config.json):

| | |
|---|---|
| Agent | Claude Code CLI 2.1.322, headless (`claude -p`), model **`claude-opus-5-5`** (requested `opus`) |
| Where | an isolated git worktree on branch `oncall/INC-20261111-052713`, at the deployed commit, outside the repo tree |
| Allowed tools | `Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash(uv run pytest:*)`, `Bash(uv run ruff:*)` |
| Denied | `.env*` (read/edit/write), `WebFetch`, `WebSearch`, `Task`, `git push`/`commit`, `gh`, `curl`, `wget`, `docker`, `uv add`, `pip`; no MCP servers (`--strict-mcp-config`); `--permission-mode dontAsk` |
| Limits | 40 turns, USD 3 budget, 20 min wall clock, no session persistence |
| Environment | allowlist only: no `GROQ_API_KEY`, no GitHub token, no Render deploy hooks, no database URL, no git credential helper |
| Prompt | [`responder-task.md`](../incident-response/responder-task.md) + the evidence packet; the answer must match [`response.schema.json`](../incident-response/response.schema.json) |
| Run | 16 turns, **USD 0.47**, 103 s |

### 4. Proposed action
From [`agent-response.json`](../incident-response/incidents/INC-20261111-052713/agent-response.json): `proposed_action: apply_fix`, confidence 0.95.
- **Root cause:** `transcriptions.py:93`, added by the deployed commit `c65a326`, divides by `result.duration_seconds` and only guards against `None`. A duration of `0.0 s` (44-byte clips) raises `ZeroDivisionError`.
- **Fix:** guard on a positive duration (`if result.duration_seconds:`) and still create the transcript. One line changed.
- **Regression test:** `test_upload_of_audio_with_zero_duration_returns_201`. It failed before the fix and passes after.

### 5. Policy decision and commands executed
[`autonomy-policy.yaml`](../incident-response/autonomy-policy.yaml) is enforced by [`responder.py`](../incident-response/responder.py), **not by the prompt**. The decision is in [`policy-decision.json`](../incident-response/incidents/INC-20261111-052713/policy-decision.json): **`apply_fix`, no failed checks.** These checks passed:
- The agent run completed.
- The answer matches the schema.
- The action is allowed and confidence ≥ 0.6.
- All changed paths are within `backend/app/**` and `backend/tests/**`, and all are regular files.
- At most 60 changed lines and 5 files.
- No tests were removed.
- No secrets in the diff.
- The new test fails on the deployed code.
- The files the agent reported match the real diff.
- The commit equals the evaluated diff.
- The git hooks and config are unchanged.
- Unit tests, `ruff check` and `ruff format` pass in a clean checkout.

Every command the responder executed is in [`commands.log`](../incident-response/incidents/INC-20261111-052713/commands.log) with its exit code and duration. In order, the responder:
1. Collected the evidence.
2. Created the worktree.
3. Ran the agent.
4. Ran the policy checks in a clean checkout.
5. Ran `git update-ref` and `git push --no-verify` to the recorded origin URL, then verified the push with `ls-remote`.
6. Ran `gh pr create --base chaos/INC-20261111-052713`, which opened **PR [#56](https://github.com/mrfmanuel/EchoNotes/pull/56)** ([screenshot](images/08-responder-pr.png)).
7. Ran `docker compose … up -d --build --no-deps --wait app` from the fixed checkout.

The responder can only deploy to the local incident stack. It has no Render deploy hooks and cannot merge.

### 6. Recovery verification
[`verification.md`](../incident-response/incidents/INC-20261111-052713/verification.md), produced by [`runbooks/verify-recovery.sh`](../incident-response/runbooks/verify-recovery.sh):

| Check | Result |
|---|---|
| health + commit | PASS: HTTP 200, commit `0e67e00` (the fix) |
| HTTP failure ratio on 20 fresh uploads (12 normal + 8 short) | PASS: 0/20 failed with 5xx |
| Prometheus failure delta | PASS: 0 failed out of 20 |
| Fixed revision is visible in telemetry | PASS: `target_info{vcs_ref_head_revision="0e67e00…"}` present, so telemetry is really flowing and not just reporting NoData |
| `scripts/smoke.sh` | PASS: the whole key journey |
| Alert | back to Normal; Grafana sent the *resolved* webhook 13 s after the rebuild started |

Timeline: alert received 05:29:15Z, then evidence, agent, policy, PR and rebuild, then verified at 05:32:54Z. **3 min 39 s** from alert to verified recovery.

### 7. Human disposition
**PR #56 was closed without merging.** This was a tech-lead decision. The fix is correct and was verified, but the code it fixes only exists on the throwaway branch `chaos/INC-20261111-052713`. `main` has no real-time-factor division, so merging would change nothing. The injected bug never reached `main`, and neither `main` nor Render dev/prod was affected.

## INC-000 (`INC-20261111-051629`): the escalation path, for real
The first live run found a **responder bug**. The Claude Code CLI rejected the response schema's `$schema` (JSON Schema draft 2020-12) in `--json-schema` and exited after 1.8 s without an answer ([`commands.log`](../incident-response/incidents/INC-20261111-051629/commands.log)).
- **What the policy did:** it treated the missing answer like any other untrustworthy output. These checks failed: `agent_run_completed`, `response_matches_schema`, `proposed_action_allowed`, `confidence_at_least_minimum`, `diff_not_empty`, `test_added_or_changed`.
- **What it produced:** [`escalation.md`](../incident-response/incidents/INC-20261111-051629/escalation.md), which tells a human what to look at. **Nothing was committed, pushed, deployed or opened as a PR.** The evidence packet was complete, so a human could still act on it.
- **Fix:** PR [#55](https://github.com/mrfmanuel/EchoNotes/pull/55). The CLI now gets the schema without `$schema` and `$id`, while the responder still validates the answer against the full contract. QA approved it after checking it with a real call. The next run was INC-001.

## Security review of the responder
QA reviewed PR #52 and its follow-ups as an attack surface ([QA report](https://github.com/mrfmanuel/EchoNotes/pull/52#issuecomment-6787204486), [re-check](https://github.com/mrfmanuel/EchoNotes/pull/52#issuecomment-6787517954), [re-check 2](https://github.com/mrfmanuel/EchoNotes/pull/52#issuecomment-6787702796)). Findings and how each was resolved:

| Finding | Risk | Fix (all with regression tests) |
|---|---|---|
| R1: agent-written code (run by pytest) plants `.git/hooks` | a denied file is committed, or a hook runs with push credentials | git runs with an empty `core.hooksPath` and `--no-verify`; the hooks, config and `info/` are snapshotted and checked; the commit is built with `write-tree`/`commit-tree` and must equal the evaluated diff |
| R2: the agent deletes a test that its fix breaks | a broken change passes "tests pass" | `no_tests_removed` |
| F1: agent code edits the operator's global `~/.gitconfig` (`pushInsteadOf`, `diff.external`) | the push is redirected, or a command runs during `git diff` | git runs with a pinned copy of the config made before the agent ran, plus `--no-ext-diff --no-textconv`; the push goes to the recorded URL and is checked with `ls-remote`; a change to the user's config escalates |
| S1–S6 | secrets in the diff, symlinks or `..` paths, git-ignored files changing test results, `.env` reads, malformed requests, PR base falling back to `main` | secret scan, `only_regular_files`, checks run in a clean checkout, `.env*` denied, 400 on bad requests, no fallback to `main` (the incident escalates instead) |

**Residual risks (accepted and documented in [on-call.md](on-call.md)):**
- The agent runs on the operator's host without an OS sandbox.
- Code it writes is executed by pytest. The environment allowlist does not stop that code from calling a credential helper by its absolute path.

Mitigations: a short-lived, local-only workflow; the push target is verified; the PR base is never `main`; a human merges.

**Telemetry privacy:**
- **Tests:** [`test_telemetry_privacy.py`](../backend/tests/unit/test_telemetry_privacy.py) runs the journey with distinctive data and asserts that no transcript text, title, filename, audio or image bytes, API key or DB URL appears in any span, metric label or log record.
- **Manual check by QA:** every distinctive value was grepped across 20 traces, 56 Loki lines and 639 series, with no hits ([PR #51 QA](https://github.com/mrfmanuel/EchoNotes/pull/51#issuecomment-6787085835)).
- **Redaction:** a span processor strips exception messages, URLs and query strings, client IP and user agent, and DB parameters.

## Not covered
These are module 4 non-goals or deliberately out of v1.0 scope:
- Semgrep and Snyk Agent Scan audits, and a `security-audit/` folder. The responder's capability table and the QA security review above cover the responder.
- An SLO, burn-rate alerts and an availability alert ([#54](https://github.com/mrfmanuel/EchoNotes/issues/54), label `future`).
- A prod telemetry backend. Telemetry is optional, and Render prod runs without a collector; Grafana Cloud OTLP is the documented next step in [observability.md](observability.md).
