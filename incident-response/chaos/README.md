# Chaos patches (injected bugs for the on-call demo)

A chaos patch is a deliberately buggy change, stored as a **patch file on `main`, never applied
on `main`**. `incident-response/test-incident.sh` is the only thing that applies it, and only
inside a throwaway git worktree:

```text
origin/main ──► chaos/INC-<id>   (worktree + this patch committed; pushed as the PR base)
                    └──► oncall/INC-<id>   (the responder's fix; PR base = chaos/INC-<id>)
```

So the responder PR diff shows only the fix, and the bug can only reach `main` if someone opened
a PR from a `chaos/*` branch to `main`, which the process forbids. The demo PR is closed without
merging. `test-incident.sh --cleanup --delete-remote` deletes the branches afterwards.

## `realtime-factor-zero-division.patch`

| | |
|---|---|
| Where | `backend/app/services/transcriptions.py`, `_transcribe()` (the transcription path, not the fake provider) |
| Change | logs a "real-time factor" (`elapsed / audio duration`), guarded only against `None` |
| Bug | `ZeroDivisionError` when the provider reports `duration_seconds == 0.0` |
| Who is hit | very short clips: accidental record-and-stop taps (header-only audio). With the `fake` provider: uploads under 80 bytes, whose duration rounds to `0.0` |
| User impact | `POST /api/projects/{id}/transcriptions` answers **500**, counted as `status="server_error"` |
| Evidence | `app.error` log `unhandled exception`, `exc_type=ZeroDivisionError`, stack trace ending at the injected line in `app/services/transcriptions.py`; the failing traces have the same trace id |
| Why the tests miss it | every existing test uploads audio with a non-zero duration (or a stub that returns `None`). With the patch, the full backend suite still passes: 446 unit + Postgres integration tests on `main` at `cb17042`, and 456 unit tests on the #29 instrumentation branch. CI would have shipped it |
| Expected fix | treat a zero duration like a missing one (`if result.duration_seconds:`), plus a unit test that uploads a header-only clip |

`incident-response/traffic.py` sends 2 of every 5 uploads as such taps, so about 40 % of the
transcriptions fail while the bug is deployed (alert threshold: 20 %). On `main` the same traffic
gets 100 % `201`.

## Re-validate after changes to `transcriptions.py`

The patch has 2 lines of context. If `transcriptions.py` changes on `main`, check it still
applies and still escapes the tests:

```bash
git worktree add --detach ../chaos-check origin/main
cd ../chaos-check
git apply --check incident-response/chaos/realtime-factor-zero-division.patch   # must apply
git apply incident-response/chaos/realtime-factor-zero-division.patch
(cd backend && TRANSCRIBER_PROVIDER=fake uv run pytest -m "not integration" -q)  # must pass
cd - && git worktree remove --force ../chaos-check
```

If it no longer applies, re-create it: make the same edit on a clean `main` checkout, then
`git diff -U2 backend/app/services/transcriptions.py > incident-response/chaos/realtime-factor-zero-division.patch`
and revert the edit. `test-incident.sh` tries `git apply --3way` and stops with a clear error if
the patch does not apply.
