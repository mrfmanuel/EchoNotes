# Escalation INC-20261111-051629

**Reason:** policy checks failed
**Failed policy checks:** agent_run_completed, response_matches_schema, proposed_action_allowed, confidence_at_least_minimum, diff_not_empty, test_added_or_changed

Nothing was pushed or deployed by the responder.
Nothing was committed to a branch.

## What a human should do
1. Open the dashboard and the runbook linked in `alert.json` (user impact first).
2. Read `evidence.json` (error logs + stack traces, failing traces, recent commits).
3. If a recent deploy correlates, roll back (docs/release-process.md) before fixing.
4. Inspect the agent's proposal in `agent-response.json` and the uncommitted worktree `incident-response/.work/oncall-INC-20261111-051629` (branch `oncall/INC-20261111-051629`).
5. Fix through a normal issue + PR (CI + QA gate).
