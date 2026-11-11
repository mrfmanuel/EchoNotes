# Incident report INC-20261111-052713

| | |
|---|---|
| Status | **resolved_verified** |
| Opened / finished (UTC) | 2026-11-11T05:29:15.180732+00:00 / 2026-11-11T05:32:54.154977+00:00 |
| Alert | EchoNotes transcription failure ratio high (page, transcription) |
| Deployed version | 0.1.0 `c65a32694456a16381b5af69e7aeba029a6bfa9c` (local) |
| Fix commit | `0e67e00332012ce5ae617dda159a8cce5c83c391` on `oncall/INC-20261111-052713` |
| Pull request | https://github.com/mrfmanuel/EchoNotes/pull/56 (base `chaos/INC-20261111-052713`) |

## User impact
Failure ratio (2 min) at collection time: **0.4023032330717067**
(alert threshold 0.2).

| Provider | Status | Count (5 min) |
|---|---|---|
| fake | success | 110.13884109622708 |
| fake | server_error | 73.4258940641514 |

## Evidence inspected
`evidence.json`: 50 error log lines
(source loki), 3 traces,
10 recent commits.
Collection errors: none.

## Model and configuration
Models: ['claude-opus-5-5'] (requested `opus`), turns
16, cost USD 0.4704566, wall 102.82 s,
stub agent: False. Limits: max turns 40, budget USD
3.0, timeout 1200 s. Exact command in
`agent-config.json` and `commands.log`.

## Proposed action
`apply_fix` (confidence 0.95).

**Root cause (agent):** backend/app/services/transcriptions.py:93 (added by commit c65a326, 'log the real-time factor') computes `elapsed_ms / 1000 / result.duration_seconds` and only guards against None. When the provider reports a duration of 0.0, this raises ZeroDivisionError and the request returns 500 (status=server_error). Only very short uploads trigger it. The fake provider computes the duration as round(size / 16000, 2), so any file under about 80 bytes gets 0.0 s. Every failing trace has echonotes.audio.size_bytes=44, which is an empty WAV header. Normal-length uploads have a positive duration and succeed.

**Summary:** INC-20261111-052713: about 40% of transcriptions failed with HTTP 500 after commit c65a326 was deployed. That commit added a real-time-factor log field. It divides by the audio duration the provider reports and only checks for None, so very short clips with a reported duration of 0.0 s (here, 44-byte empty WAV files) raised ZeroDivisionError. The fix changes the guard to a truthiness check: the factor is logged only when the duration is positive, and the transcript is still created. A new unit test uploads a 44-byte WAV through the fake provider and expects 201. It failed with ZeroDivisionError before the fix and passes after. All 457 unit tests pass, and ruff check and ruff format --check are clean. The log fields are unchanged apart from leaving out realtime_factor in that case. No transcript text, titles or filenames are logged.

## Policy decision (enforced in code): `apply_fix`

| Check | Result | Detail |
|---|---|---|
| agent_run_completed | pass | subtype=success |
| response_matches_schema | pass | valid |
| proposed_action_allowed | pass | proposed_action='apply_fix', allowed=['apply_fix'] |
| confidence_at_least_minimum | pass | confidence=0.95, minimum=0.6 |
| diff_not_empty | pass | 2 changed file(s) |
| paths_allowed | pass | all inside |
| only_regular_files | pass | regular files |
| max_changed_lines | pass | 14 changed lines, max 60 |
| max_changed_files | pass | 2 files, max 5 |
| no_tests_removed | pass | no test file deleted, no test function removed |
| test_added_or_changed | pass | 12 added test lines in ['backend/tests/unit/test_transcriptions_api.py'] |
| report_matches_diff | pass | agent claimed ['backend/app/services/transcriptions.py', 'backend/tests/unit/test_transcriptions_api.py'], git diff shows ['backend/app/services/transcriptions.py', 'backend/tests/unit/test_transcriptions_api.py'] |
| commit_matches_evaluated_diff | pass | candidate commit == evaluated diff |
| no_secrets_in_diff | pass | no secret patterns in added lines |
| new_test_fails_before_fix | pass | pytest exit 1 on the deployed code (want 1 = failed, with a pytest 'failed' summary) |
| unit_tests_pass | pass | exit 0 |
| lint_pass | pass | exit 0 |
| format_pass | pass | exit 0 |

## Commands executed
See `commands.log` (every command with its exit code and duration).

## Recovery verification
See `verification.md`.


## Disposition of the PR
The PR targets the throwaway incident base branch, not `main`. A human closes it without merging
(the bug only existed on the incident branch) unless the fix is a genuine hardening for `main`,
in which case it is re-opened against `main` through the normal CI + QA gate.
