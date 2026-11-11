# Incident report INC-20261111-051629

| | |
|---|---|
| Status | **escalated** |
| Opened / finished (UTC) | 2026-11-11T05:18:55.130845+00:00 / 2026-11-11T05:19:20.341592+00:00 |
| Alert | EchoNotes transcription failure ratio high (page, transcription) |
| Deployed version | 0.1.0 `66ceb74f40fec7b66b70b8522ae46bedea0f3e91` (local) |
| Fix commit | `none` on `oncall/INC-20261111-051629` |
| Pull request | none (base `n/a`) |

## User impact
Failure ratio (2 min) at collection time: **0.3894403443530037**
(alert threshold 0.2).

| Provider | Status | Count (5 min) |
|---|---|---|
| fake | success | 110.61957640264785 |
| fake | server_error | 70.50033691040677 |

## Evidence inspected
`evidence.json`: 50 error log lines
(source loki), 3 traces,
10 recent commits.
Collection errors: none.

## Model and configuration
Models: n/a (requested `opus`), turns
None, cost USD None, wall 1.82 s,
stub agent: False. Limits: max turns 40, budget USD
3.0, timeout 1200 s. Exact command in
`agent-config.json` and `commands.log`.

## Proposed action
`None` (confidence None).

**Root cause (agent):** n/a

**Summary:** n/a

## Policy decision (enforced in code): `escalate`

| Check | Result | Detail |
|---|---|---|
| agent_run_completed | FAIL | subtype=None |
| response_matches_schema | FAIL | agent returned no JSON answer |
| proposed_action_allowed | FAIL | proposed_action=None, allowed=['apply_fix'] |
| confidence_at_least_minimum | FAIL | confidence=None, minimum=0.6 |
| diff_not_empty | FAIL | 0 changed file(s) |
| paths_allowed | pass | all inside |
| only_regular_files | pass | regular files |
| max_changed_lines | pass | 0 changed lines, max 60 |
| max_changed_files | pass | 0 files, max 5 |
| no_tests_removed | pass | no test file deleted, no test function removed |
| test_added_or_changed | FAIL | 0 added test lines in [] |
| report_matches_diff | pass | agent claimed [], git diff shows [] |
| commit_matches_evaluated_diff | skipped | skipped |
| no_secrets_in_diff | skipped | skipped |
| new_test_fails_before_fix | skipped | skipped |
| unit_tests_pass | skipped | skipped (an earlier check failed) |
| lint_pass | skipped | skipped (an earlier check failed) |
| format_pass | skipped | skipped (an earlier check failed) |

## Commands executed
See `commands.log` (every command with its exit code and duration).

## Recovery verification
Not run.
Escalated: see `escalation.md`.

## Disposition of the PR
The PR targets the throwaway incident base branch, not `main`. A human closes it without merging
(the bug only existed on the incident branch) unless the fix is a genuine hardening for `main`,
in which case it is re-opened against `main` through the normal CI + QA gate.
