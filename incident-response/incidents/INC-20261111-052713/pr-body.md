## Incident INC-20261111-052713

Automated fix proposed by the on-call agent and accepted by the responder's policy checks. Base branch `chaos/INC-20261111-052713` is the deployed (incident) code, so this diff shows only the fix.

**Summary:** INC-20261111-052713: about 40% of transcriptions failed with HTTP 500 after commit c65a326 was deployed. That commit added a real-time-factor log field. It divides by the audio duration the provider reports and only checks for None, so very short clips with a reported duration of 0.0 s (here, 44-byte empty WAV files) raised ZeroDivisionError. The fix changes the guard to a truthiness check: the factor is logged only when the duration is positive, and the transcript is still created. A new unit test uploads a 44-byte WAV through the fake provider and expects 201. It failed with ZeroDivisionError before the fix and passes after. All 457 unit tests pass, and ruff check and ruff format --check are clean. The log fields are unchanged apart from leaving out realtime_factor in that case. No transcript text, titles or filenames are logged.

**Root cause:** backend/app/services/transcriptions.py:93 (added by commit c65a326, 'log the real-time factor') computes `elapsed_ms / 1000 / result.duration_seconds` and only guards against None. When the provider reports a duration of 0.0, this raises ZeroDivisionError and the request returns 500 (status=server_error). Only very short uploads trigger it. The fake provider computes the duration as round(size / 16000, 2), so any file under about 80 bytes gets 0.0 s. Every failing trace has echonotes.audio.size_bytes=44, which is an empty WAV header. Normal-length uploads have a positive duration and succeed.

**Confidence:** 0.95

### Evidence used
- logs: 50+ ERROR 'unhandled exception' lines with exc_type=ZeroDivisionError; stack trace ends at app/services/transcriptions.py line 93 in _transcribe: realtime_factor = round(elapsed_ms / 1000 / result.duration_seconds, 4)
- traces 832f1a84f3e0fd14a4ce834884348d69, e64499953538a5110cf09c565e16f2d8, 1060bb6d4280b018e5e0c935c821fdac: transcription.create error.type=ZeroDivisionError, echonotes.audio.size_bytes=44, provider=fake, HTTP 500
- metric transcriptions_by_status_5m: provider=fake status=server_error ~73 vs success ~110; failure_ratio_2m=0.40
- commit c65a32694456a16381b5af69e7aeba029a6bfa9c 'perf(transcription): log the real-time factor of each transcription' is deployed and touched only backend/app/services/transcriptions.py

### Policy checks (enforced in code)
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

Full trail: `incident-response/incidents/INC-20261111-052713/`.

Do not merge into `main` without the normal CI + QA gate.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
