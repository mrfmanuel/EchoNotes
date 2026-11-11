"""Tests for the on-call responder logic: intake/dedupe, policy enforcement, schema validation,
evidence scrubbing and the full pipeline with a stub agent (never a real model or network).

Run: make test-responder
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import collect_evidence as ce
import responder as r

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = json.loads((ROOT / "response.schema.json").read_text(encoding="utf-8"))
POLICY = r.load_policy(ROOT / "autonomy-policy.yaml")
ALERTNAME = "EchoNotes transcription failure ratio high"
RULE_UID = "echonotes-transcription-failure-ratio"


def grafana_payload(status: str = "firing", fingerprint: str = "abc123", **labels: str) -> dict:
    return {
        "receiver": "oncall-responder",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": ALERTNAME, "severity": "page", **labels},
                "annotations": {"summary": "failure ratio high", "runbook_url": "https://x"},
                "startsAt": "2026-11-10T10:00:00Z",
                "fingerprint": fingerprint,
                "generatorURL": f"http://localhost:3001/alerting/grafana/{RULE_UID}/view?orgId=1",
            }
        ],
    }


def good_answer(**overrides: Any) -> dict[str, Any]:
    answer = {
        "root_cause": "backend/app/x.py:1 divides by zero for empty clips",
        "evidence_used": ["log ZeroDivisionError"],
        "files_changed": ["backend/app/x.py", "backend/tests/unit/test_x.py"],
        "tests_added": ["backend/tests/unit/test_x.py::test_y"],
        "confidence": 0.9,
        "proposed_action": "apply_fix",
        "summary": "Guard the division so empty clips no longer fail.",
    }
    answer.update(overrides)
    return answer


OK_META = {"subtype": "success", "is_error": False}
GOOD_CHANGES = [
    r.FileChange("backend/app/x.py", 3, 1, "M"),
    r.FileChange("backend/tests/unit/test_x.py", 6, 0, "A"),
]


def passing_runner(_name: str, argv: list[str]) -> r.CmdResult:
    return r.CmdResult(argv, 0, "", 0.1)


def failing_tests_runner(name: str, argv: list[str]) -> r.CmdResult:
    return r.CmdResult(argv, 1 if name == "unit_tests_pass" else 0, "", 0.1)


def repro_fails(_tests: list[str]) -> r.CmdResult:
    return r.CmdResult([], 1, "", 0.1)


def evaluate(
    answer: Any = None,
    changes: list[r.FileChange] | None = None,
    runner: r.CommandRunner = passing_runner,
    reproduce: Any = repro_fails,
    meta: dict[str, Any] | None = None,
    policy: dict[str, Any] = POLICY,
    candidate: Any = "same",
) -> dict[str, Any]:
    """`candidate="same"`: the candidate commit has exactly the evaluated diff, no secrets."""
    answer = good_answer() if answer is None else answer
    changes = GOOD_CHANGES if changes is None else changes
    if candidate == "same":
        candidate = lambda: (list(changes), "")  # noqa: E731
    return r.evaluate_policy(
        policy,
        OK_META if meta is None else meta,
        answer,
        r.validate_response(answer, SCHEMA),
        changes,
        runner,
        reproduce,
        candidate,
    )


def by_name(decision: dict[str, Any]) -> dict[str, Any]:
    return {c["name"]: c["passed"] for c in decision["checks"]}


# --- intake and dedupe ---


def test_first_firing_alert_opens_one_incident(tmp_path: Path) -> None:
    registry = r.Registry(tmp_path / "state.json")
    intake = registry.intake(grafana_payload(), POLICY)
    assert [key for key, _ in intake.new] == [f"{RULE_UID}:abc123"]


def test_repeated_firing_alert_with_open_incident_is_deduplicated(tmp_path: Path) -> None:
    registry = r.Registry(tmp_path / "state.json")
    key, _ = registry.intake(grafana_payload(), POLICY).new[0]
    registry.register(key, "INC-20261110-100000")
    repeat = registry.intake(grafana_payload(), POLICY)
    assert repeat.new == []
    assert "duplicate of INC-20261110-100000" in repeat.ignored[0]["reason"]


def test_dedupe_survives_a_responder_restart(tmp_path: Path) -> None:
    first = r.Registry(tmp_path / "state.json")
    key, _ = first.intake(grafana_payload(), POLICY).new[0]
    first.register(key, "INC-20261110-100000")
    assert r.Registry(tmp_path / "state.json").intake(grafana_payload(), POLICY).new == []


def test_resolved_notification_never_opens_an_incident_and_closes_the_open_one(
    tmp_path: Path,
) -> None:
    registry = r.Registry(tmp_path / "state.json")
    assert registry.intake(grafana_payload("resolved"), POLICY).new == []
    key, _ = registry.intake(grafana_payload(), POLICY).new[0]
    registry.register(key, "INC-20261110-100000")
    resolved = registry.intake(grafana_payload("resolved"), POLICY)
    assert resolved.new == [] and resolved.resolved == [(key, "INC-20261110-100000")]
    assert len(registry.intake(grafana_payload(), POLICY).new) == 1  # it may fire again later


def test_duplicate_alerts_in_one_batch_open_one_incident(tmp_path: Path) -> None:
    payload = grafana_payload()
    payload["alerts"].append(copy.deepcopy(payload["alerts"][0]))
    assert len(r.Registry(tmp_path / "s.json").intake(payload, POLICY).new) == 1


def test_alert_outside_the_policy_allowlist_is_ignored(tmp_path: Path) -> None:
    payload = grafana_payload()
    payload["alerts"][0]["labels"]["alertname"] = "CPU high"
    payload["alerts"][0]["generatorURL"] = "http://x/alerting/grafana/cpu/view"
    intake = r.Registry(tmp_path / "s.json").intake(payload, POLICY)
    assert intake.new == [] and intake.ignored[0]["reason"] == "alert not in policy allowlist"


def test_payload_without_alerts_is_ignored(tmp_path: Path) -> None:
    intake = r.Registry(tmp_path / "s.json").intake({"status": "firing"}, POLICY)
    assert intake.new == [] and intake.ignored


def test_rule_uid_comes_from_the_label_or_the_generator_url() -> None:
    alert = grafana_payload()["alerts"][0]
    assert r.alert_rule_uid(alert) == RULE_UID
    alert["labels"]["__alert_rule_uid__"] = "other"
    assert r.alert_rule_uid(alert) == "other"


def test_rule_uid_prefers_grafanas_rule_uid_field() -> None:
    alert = {**grafana_payload()["alerts"][0], "ruleUID": "from-field", "generatorURL": ""}
    assert r.alert_rule_uid(alert) == "from-field"
    assert r.dedupe_key(alert) == "from-field:abc123"


def test_incident_id_has_the_utc_timestamp_format() -> None:
    assert r.INCIDENT_ID_RE.match(r.new_incident_id())


# --- schema validation and agent output parsing ---


def test_valid_answer_matches_the_schema() -> None:
    assert r.validate_response(good_answer(), SCHEMA) == []


@pytest.mark.parametrize(
    "broken",
    [
        {"proposed_action": "deploy_to_prod"},
        {"confidence": 1.5},
        {"evidence_used": []},
        {"unexpected": "field"},
    ],
)
def test_invalid_answers_are_rejected_by_the_schema(broken: dict[str, Any]) -> None:
    assert r.validate_response(good_answer(**broken), SCHEMA)


def test_missing_answer_is_a_schema_error() -> None:
    assert r.validate_response(None, SCHEMA) == ["agent returned no JSON answer"]


def test_agent_output_prefers_structured_output() -> None:
    envelope = {
        "type": "result",
        "subtype": "success",
        "structured_output": {"a": 1},
        "result": "ignored",
        "modelUsage": {"claude-x": {}},
    }
    meta, answer = r.parse_agent_output(json.dumps(envelope))
    assert answer == {"a": 1} and meta["models"] == ["claude-x"]


def test_agent_output_falls_back_to_a_fenced_json_result() -> None:
    envelope = {"type": "result", "subtype": "success", "result": 'Done.\n```json\n{"a": 2}\n```'}
    assert r.parse_agent_output(json.dumps(envelope))[1] == {"a": 2}


def test_non_json_agent_output_yields_no_answer() -> None:
    meta, answer = r.parse_agent_output("Error: something")
    assert answer is None and "parse_error" in meta


# --- policy enforcement (in code) ---


def test_policy_applies_a_small_tested_fix_inside_the_allowlist() -> None:
    decision = evaluate()
    assert decision["decision"] == "apply_fix", decision["failed_checks"]
    assert all(c["passed"] for c in decision["checks"])


def test_policy_escalates_a_change_outside_the_allowed_paths() -> None:
    changes = [*GOOD_CHANGES, r.FileChange("frontend/src/App.tsx", 1, 0)]
    answer = good_answer(files_changed=[c.path for c in changes])
    decision = evaluate(answer, changes)
    assert decision["decision"] == "escalate"
    assert by_name(decision)["paths_allowed"] is False


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "Dockerfile",
        "docker-compose.yml",
        "backend/.env",
        "incident-response/autonomy-policy.yaml",
        "observability/alerts.yaml",
        "backend/pyproject.toml",
    ],
)
def test_policy_escalates_a_change_to_a_denied_path(path: str) -> None:
    changes = [*GOOD_CHANGES, r.FileChange(path, 1, 0)]
    decision = evaluate(good_answer(files_changed=[c.path for c in changes]), changes)
    assert by_name(decision)["paths_allowed"] is False
    assert decision["decision"] == "escalate"


def test_denied_glob_wins_over_the_allowlist() -> None:
    assert r.path_matches("backend/app/.env.local", POLICY["changes"]["denied_paths"])
    assert r.path_matches("backend/app/.env.local", POLICY["changes"]["allowed_paths"])


def test_policy_escalates_too_many_changed_lines() -> None:
    changes = [r.FileChange("backend/app/x.py", 70, 0), GOOD_CHANGES[1]]
    decision = evaluate(changes=changes)
    assert by_name(decision)["max_changed_lines"] is False
    assert decision["decision"] == "escalate"


def test_policy_escalates_when_unit_tests_fail() -> None:
    decision = evaluate(runner=failing_tests_runner)
    assert by_name(decision)["unit_tests_pass"] is False
    assert decision["decision"] == "escalate"


def test_policy_escalates_when_the_new_test_does_not_fail_before_the_fix() -> None:
    decision = evaluate(reproduce=lambda _t: r.CmdResult([], 0, "", 0.1))
    assert by_name(decision)["new_test_fails_before_fix"] is False


def test_policy_escalates_a_fix_without_a_test() -> None:
    changes = [GOOD_CHANGES[0]]
    decision = evaluate(good_answer(files_changed=["backend/app/x.py"]), changes)
    assert by_name(decision)["test_added_or_changed"] is False


def test_policy_escalates_a_deleted_test_file() -> None:  # QA R2
    changes = [*GOOD_CHANGES, r.FileChange("backend/tests/unit/test_guard.py", 0, 7, "D")]
    decision = evaluate(good_answer(files_changed=[c.path for c in changes]), changes)
    assert by_name(decision)["no_tests_removed"] is False
    assert decision["decision"] == "escalate"


def test_policy_escalates_removed_test_functions() -> None:  # QA R2
    changes = [
        GOOD_CHANGES[0],
        r.FileChange("backend/tests/unit/test_x.py", 2, 5, "M", "100644", 1),
    ]
    decision = evaluate(good_answer(files_changed=[c.path for c in changes]), changes)
    assert by_name(decision)["no_tests_removed"] is False


def test_only_deleted_test_lines_do_not_count_as_a_test_change() -> None:  # QA R2
    changes = [GOOD_CHANGES[0], r.FileChange("backend/tests/unit/test_x.py", 0, 3, "M")]
    decision = evaluate(good_answer(files_changed=[c.path for c in changes]), changes)
    assert by_name(decision)["test_added_or_changed"] is False


@pytest.mark.parametrize(
    "change",
    [
        r.FileChange("backend/app/link.py", 1, 0, "A", "120000"),  # symlink
        r.FileChange("backend/app/sub", 1, 0, "A", "160000"),  # submodule
        r.FileChange("backend/app/../../.github/x.yml", 1, 0, "A"),
    ],
)
def test_policy_escalates_symlinks_submodules_and_unsafe_paths(change: r.FileChange) -> None:
    changes = [*GOOD_CHANGES, change]  # QA S2
    decision = evaluate(good_answer(files_changed=[c.path for c in changes]), changes)
    assert by_name(decision)["only_regular_files"] is False


def test_policy_escalates_when_the_commit_differs_from_the_evaluated_diff() -> None:  # QA R1
    sneaky = [*GOOD_CHANGES, r.FileChange(".github/workflows/evil.yml", 1, 0, "A")]
    decision = evaluate(candidate=lambda: (sneaky, ""))
    assert by_name(decision)["commit_matches_evaluated_diff"] is False
    assert by_name(decision)["unit_tests_pass"] is None  # nothing ran afterwards


def test_policy_escalates_secrets_in_the_added_lines() -> None:  # QA S1
    decision = evaluate(candidate=lambda: (list(GOOD_CHANGES), 'KEY = "gsk_abcdefghijklmnop"'))
    assert by_name(decision)["no_secrets_in_diff"] is False


def test_policy_without_a_candidate_commit_never_applies() -> None:
    decision = evaluate(candidate=None)
    assert decision["decision"] == "escalate"


def test_policy_escalates_when_the_agent_misreports_its_files() -> None:
    decision = evaluate(good_answer(files_changed=["backend/app/x.py"]))
    assert by_name(decision)["report_matches_diff"] is False


def test_policy_escalates_when_the_agent_proposes_escalation() -> None:
    decision = evaluate(good_answer(proposed_action="escalate"))
    assert by_name(decision)["proposed_action_allowed"] is False


def test_policy_escalates_low_confidence() -> None:
    assert by_name(evaluate(good_answer(confidence=0.3)))["confidence_at_least_minimum"] is False


def test_policy_escalates_a_schema_violation_and_skips_running_code() -> None:
    calls: list[str] = []

    def runner(name: str, argv: list[str]) -> r.CmdResult:
        calls.append(name)
        return r.CmdResult(argv, 0, "", 0.0)

    decision = evaluate(good_answer(confidence="high"), runner=runner)
    assert by_name(decision)["response_matches_schema"] is False
    assert calls == []  # agent code is never executed when static checks fail
    assert by_name(decision)["unit_tests_pass"] is None


def test_policy_escalates_an_agent_run_that_hit_a_limit() -> None:
    decision = evaluate(meta={"subtype": "error_max_turns", "is_error": True})
    assert by_name(decision)["agent_run_completed"] is False


def test_policy_escalates_an_empty_diff() -> None:
    decision = evaluate(good_answer(files_changed=[]), changes=[])
    assert by_name(decision)["diff_not_empty"] is False


# --- sandbox and agent command ---


def test_agent_environment_drops_credentials(tmp_path: Path) -> None:
    base = {
        "PATH": "/bin",
        "GROQ_API_KEY": "gsk_x",
        "GH_TOKEN": "ghp_x",
        "GITHUB_TOKEN": "t",
        "DATABASE_URL": "postgresql://u:p@h/db",
        "RENDER_DEPLOY_HOOK_PROD": "https://hook",
        "ONCALL_STUB_SCENARIO": "good_fix",
    }
    env = r.sandbox_env(base, tmp_path)
    for name in (
        "GROQ_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "DATABASE_URL",
        "RENDER_DEPLOY_HOOK_PROD",
    ):
        assert name not in env
    assert env["TRANSCRIBER_PROVIDER"] == "fake" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["ONCALL_STUB_SCENARIO"] == "good_fix"


def test_claude_command_has_the_restricting_flags() -> None:
    argv = r.claude_argv(POLICY, SCHEMA)
    for flag in (
        "-p",
        "--output-format",
        "--json-schema",
        "--max-turns",
        "--max-budget-usd",
        "--allowedTools",
        "--disallowedTools",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--permission-mode",
    ):
        assert flag in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    allowed = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
    assert "Bash(uv run pytest:*)" in allowed and "WebFetch" not in allowed
    assert not any(tool.startswith("Bash(git") for tool in allowed)
    assert "WebFetch" in argv[argv.index("--disallowedTools") + 1 :]


# --- evidence scrubbing ---


def test_scrub_redacts_secrets_and_drops_user_content() -> None:
    dirty = {
        "message": "call failed with key gsk_abcdefghijklmnopqrstu",
        "url": "postgresql+psycopg://echonotes:supersecret@db:5432/echonotes",
        "header": "Authorization: Bearer abc.def.ghijklmnop",
        "token_line": "token=ghp_abcdefghijklmnopqrstuvwxyz0123",
        "text": "the transcript itself",
        "title": "Lecture about secrets",
        "source_filename": "my-private-file.m4a",
        "exception.message": "could echo input",
        "nested": [{"authorization": "Basic Zm9vOmJhcg==", "provider": "fake"}],
    }
    clean = json.dumps(ce.scrub(dirty))
    for leaked in (
        "gsk_abc",
        "supersecret",
        "abc.def",
        "ghp_abc",
        "the transcript itself",
        "Lecture about",
        "my-private-file",
        "could echo",
        "Zm9vOmJhcg",
    ):
        assert leaked not in clean
    assert '"provider": "fake"' in clean


def test_log_records_keep_only_allowlisted_fields() -> None:
    record = ce.allowlisted_log(
        {
            "level": "ERROR",
            "exc_type": "ZeroDivisionError",
            "trace_id": "a" * 32,
            "stack_trace": "x" * 10_000,
            "title": "secret",
            "filename": "f.m4a",
            "exception.stacktrace": "frames",
            "random_field": 1,
        }
    )
    assert set(record) == {"level", "exc_type", "trace_id", "stack_trace", "exception_stacktrace"}
    assert len(record["stack_trace"]) < 5000


def test_loki_response_is_parsed_into_allowlisted_records() -> None:
    line = json.dumps({"level": "ERROR", "message": "unhandled exception", "text": "leak"})
    payload = {
        "data": {
            "result": [
                {
                    "stream": {
                        "service_name": "echonotes-api",
                        "trace_id": "b" * 32,
                        "exception_type": "ZeroDivisionError",
                    },
                    "values": [["1731232800000000000", line]],
                }
            ]
        }
    }
    [record] = ce.parse_loki(payload)
    assert record["trace_id"] == "b" * 32 and record["exception_type"] == "ZeroDivisionError"
    assert "text" not in record and record["message"] == "unhandled exception"


def test_container_logs_keep_only_error_records() -> None:
    text = (
        'app-1  | {"level": "INFO", "message": "request completed"}\n'
        'app-1  | {"level": "ERROR", "exc_type": "ZeroDivisionError", "title": "x"}\n'
        "app-1  | not json\n"
    )
    assert ce.parse_container_logs(text) == [{"level": "ERROR", "exc_type": "ZeroDivisionError"}]


def test_trace_is_reduced_to_allowlisted_span_attributes() -> None:
    attr = lambda k, v: {"key": k, "value": {"stringValue": v}}  # noqa: E731
    payload = {
        "batches": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "spanId": "AAAAAAAAAAE=",
                                "name": "transcription.create",
                                "startTimeUnixNano": "1000000",
                                "endTimeUnixNano": "3000000",
                                "status": {"code": "STATUS_CODE_ERROR"},
                                "attributes": [
                                    attr("echonotes.provider", "fake"),
                                    attr("error.type", "ZeroDivisionError"),
                                    attr("http.url", "http://x/?q=secret"),
                                    attr("db.statement", "SELECT"),
                                ],
                                "events": [
                                    {
                                        "name": "exception",
                                        "attributes": [
                                            attr("exception.message", "user input"),
                                            attr("exception.type", "ZeroDivisionError"),
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    trace = ce.reduce_trace("c" * 32, payload)
    span = trace["spans"][0]
    assert span["attributes"] == {"echonotes.provider": "fake", "error.type": "ZeroDivisionError"}
    assert span["events"][0]["attributes"] == {"exception.type": "ZeroDivisionError"}
    assert span["duration_ms"] == 2.0 and span["span_id"] == "0000000000000001"


def test_prometheus_nan_values_become_null() -> None:
    payload = {"data": {"result": [{"metric": {}, "value": [0, "NaN"]}]}}
    assert ce.parse_prometheus(payload) == [{"labels": {}, "value": None}]


def test_only_allowlisted_grafana_paths_can_be_queried() -> None:
    collector = ce.Collector({}, http_get=lambda url, headers: (200, {}))
    with pytest.raises(ValueError):
        collector._grafana("/api/admin/users")


def test_collect_builds_a_scrubbed_packet_from_canned_sources(tmp_path: Path) -> None:
    def fake_get(url: str, headers: dict[str, str] | None) -> tuple[int, Any]:
        if url.endswith("/api/health"):
            return 200, {
                "status": "ok",
                "commit": "f" * 40,
                "environment": "local",
                "version": "1.0.0",
                "database": "ok",
            }
        if "/prometheus/" in url:
            return 200, {
                "data": {"result": [{"metric": {"status": "server_error"}, "value": [0, "8"]}]}
            }
        if "/loki/" in url:
            line = json.dumps(
                {
                    "level": "ERROR",
                    "exc_type": "ZeroDivisionError",
                    "trace_id": "d" * 32,
                    "message": "key gsk_abcdefghijklmnop",
                }
            )
            return 200, {"data": {"result": [{"stream": {}, "values": [["1", line]]}]}}
        if "/tempo/api/traces/" in url:
            return 200, {"batches": []}
        return 200, {"traces": []}

    evidence = ce.collect("INC-20261110-100000", tmp_path, env={}, http_get=fake_get)
    assert evidence["deployment"]["commit"] == "f" * 40
    assert evidence["logs"]["lines"][0]["exc_type"] == "ZeroDivisionError"
    assert [t["trace_id"] for t in evidence["traces"]] == ["d" * 32]
    assert "gsk_abc" not in json.dumps(evidence)


# --- full pipeline with a stub agent in a throwaway git repo ---

BUGGY = (
    "def ratio(numerator: float, denominator: float) -> float:\n"
    "    return numerator / denominator\n"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "tests" / "unit").mkdir(parents=True)
    (repo / "backend" / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "backend" / "app" / "calc.py").write_text(BUGGY, encoding="utf-8")
    (repo / "backend" / "pytest.ini").write_text(
        "[pytest]\npythonpath = .\nmarkers =\n    integration: needs Postgres\n", encoding="utf-8"
    )
    (repo / "backend" / "tests" / "unit" / "test_calc.py").write_text(
        "from app.calc import ratio\n\n\ndef test_ratio() -> None:\n    assert ratio(4, 2) == 2\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    policy = copy.deepcopy(POLICY)
    pytest_argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    policy["checks"].update(
        unit_tests=pytest_argv,
        lint=[sys.executable, "-c", "pass"],
        format=[sys.executable, "-c", "pass"],
        timeout_seconds=120,
    )
    policy["agent"]["timeout_seconds"] = 60
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")  # JSON is valid YAML

    env = {
        "ONCALL_REPO": str(repo),
        "ONCALL_INCIDENTS_DIR": str(tmp_path / "incidents"),
        "ONCALL_WORK_DIR": str(tmp_path / "work"),
        "ONCALL_POLICY": str(policy_path),
        "ONCALL_AGENT_CMD": json.dumps([sys.executable, str(HERE / "stub_agent.py")]),
        "ONCALL_EVIDENCE_CMD": json.dumps([sys.executable, str(HERE / "stub_evidence.py")]),
        "ONCALL_PUBLISH": "0",
        "ONCALL_DEPLOY": "0",
        "GROQ_API_KEY": "gsk_must_not_reach_the_agent",
        "ONCALL_STUB_MARKER": str(tmp_path / "hook-marker.txt"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # The pipeline's own `uv sync` step is not needed in the toy repo.
    real_run = r.IncidentLog.run

    def run(self: r.IncidentLog, argv: Any, *args: Any, **kwargs: Any) -> r.CmdResult:
        if list(argv[:2]) == ["uv", "sync"]:
            return r.CmdResult(list(argv), 0, "", 0.0)
        return real_run(self, argv, *args, **kwargs)

    monkeypatch.setattr(r.IncidentLog, "run", run)
    return {
        "repo": repo,
        "incidents": tmp_path / "incidents",
        "marker": tmp_path / "hook-marker.txt",
    }


def run_incident(scenario: str, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path]:
    monkeypatch.setenv("ONCALL_STUB_SCENARIO", scenario)
    responder = r.Responder(r.Config.from_env())
    accepted = responder.handle(grafana_payload())["accepted"]
    assert len(accepted) == 1
    responder.exit_after = 1
    responder.worker()
    folder = responder.cfg.incidents_dir / accepted[0]
    return json.loads((folder / "incident.json").read_text(encoding="utf-8")), folder


def test_pipeline_commits_a_policy_approved_fix_on_the_oncall_branch(
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, folder = run_incident("good_fix", monkeypatch)
    assert state["status"] == "fix_committed", (folder / "commands.log").read_text("utf-8")
    for name in (
        "alert.json",
        "evidence.json",
        "agent-config.json",
        "agent-response.json",
        "policy-decision.json",
        "commands.log",
        "verification.md",
        "report.md",
    ):
        assert (folder / name).exists(), name
    assert not (folder / "escalation.md").exists()
    decision = json.loads((folder / "policy-decision.json").read_text("utf-8"))
    assert decision["decision"] == "apply_fix"
    assert by_name(decision)["new_test_fails_before_fix"] is True
    subject = _git(sandbox["repo"], "log", "-1", "--format=%s", state["branch"])
    assert subject.startswith("fix(calc): ") and subject.endswith(f"({state['incident_id']})")
    assert _git(sandbox["repo"], "rev-parse", "main") != state["fix_commit"]  # main untouched
    response = json.loads((folder / "agent-response.json").read_text("utf-8"))
    assert response["schema_errors"] == []
    evidence = (folder / "evidence.json").read_text("utf-8")
    assert "Bearer abcdefghijklmnop" not in evidence  # re-scrubbed by the responder


@pytest.mark.parametrize(
    ("scenario", "failed_check"),
    [
        ("denied_path", "paths_allowed"),
        ("too_many_lines", "max_changed_lines"),
        ("breaks_tests", "unit_tests_pass"),
        ("misreported_files", "report_matches_diff"),
        ("escalate", "proposed_action_allowed"),
        ("low_confidence", "confidence_at_least_minimum"),
        ("invalid_json", "response_matches_schema"),
        ("schema_violation", "response_matches_schema"),
        ("delete_test", "no_tests_removed"),  # QA R2
        ("leak_secret", "no_secrets_in_diff"),  # QA S1
    ],
)
def test_pipeline_escalates_and_commits_nothing_when_a_check_fails(
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch, scenario: str, failed_check: str
) -> None:
    head_before = _git(sandbox["repo"], "rev-parse", "main")
    state, folder = run_incident(scenario, monkeypatch)
    assert state["status"] == "escalated"
    assert (folder / "escalation.md").exists() and (folder / "report.md").exists()
    decision = json.loads((folder / "policy-decision.json").read_text("utf-8"))
    assert failed_check in decision["failed_checks"]
    branch_head = _git(sandbox["repo"], "rev-parse", state["branch"])
    assert branch_head == head_before  # nothing committed on the oncall branch
    assert "fix_commit" not in state


@pytest.mark.parametrize("scenario", ["plant_hook", "plant_hook_via_test"])
def test_pipeline_planted_git_hooks_never_run_and_escalate(  # QA R1 regression
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    repo = sandbox["repo"]
    head_before = _git(repo, "rev-parse", "main")
    state, folder = run_incident(scenario, monkeypatch)
    assert state["status"] == "escalated"
    assert "git metadata modified" in state["escalation_reason"]
    assert not sandbox["marker"].exists(), "a planted hook ran"
    assert _git(repo, "rev-parse", state["branch"]) == head_before  # nothing committed
    assert "fix_commit" not in state and not state.get("pushed")
    hooks = Path(_git(repo, "rev-parse", "--git-common-dir"))
    hooks = (hooks if hooks.is_absolute() else repo / hooks) / "hooks"
    planted = [p.name for p in hooks.glob("*") if not p.name.endswith(".sample")]
    assert planted == [], f"planted hooks were not removed: {planted}"
    all_files = _git(repo, "log", "--all", "--name-only", "--format=")
    assert ".github/workflows/evil.yml" not in all_files


def test_pipeline_never_falls_back_to_main_as_pr_base(  # QA S6
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONCALL_PUBLISH", "1")
    monkeypatch.delenv("ONCALL_PR_BASE", raising=False)
    state, _folder = run_incident("good_fix", monkeypatch)
    assert state["status"] == "escalated" and "no PR base" in state["escalation_reason"]
    assert not state.get("pushed") and "pr_url" not in state


def test_pipeline_escalates_when_the_deployed_commit_is_unknown(
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "no_commit_evidence.py"
    script.write_text(
        "import argparse, json\np = argparse.ArgumentParser()\n"
        "[p.add_argument(a) for a in ('--incident-id', '--out', '--repo', '--alert')]\n"
        "a = p.parse_args()\njson.dump({'deployment': {'commit': 'unknown'}}, open(a.out, 'w'))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ONCALL_EVIDENCE_CMD", json.dumps([sys.executable, str(script)]))
    state, folder = run_incident("good_fix", monkeypatch)
    assert (
        state["status"] == "escalated" and "deployed commit unknown" in state["escalation_reason"]
    )


def test_stub_agent_never_sees_credentials(
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _state, folder = run_incident("good_fix", monkeypatch)
    config = json.loads((folder / "agent-config.json").read_text("utf-8"))
    assert "GROQ_API_KEY" not in config["env_names_passed"]
    assert config["stub"] is True


# --- HTTP server ---


def test_webhook_server_accepts_once_and_deduplicates(
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONCALL_PORT", "0")
    responder = r.Responder(r.Config.from_env())
    started: list[str] = []
    monkeypatch.setattr(responder, "worker", lambda: None)
    responder.jobs.put = lambda job: started.append(job[0])  # type: ignore[method-assign]

    from http.server import ThreadingHTTPServer  # noqa: PLC0415

    servers: list[ThreadingHTTPServer] = []
    real_init = ThreadingHTTPServer.__init__

    def capture(self: ThreadingHTTPServer, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        servers.append(self)

    monkeypatch.setattr(ThreadingHTTPServer, "__init__", capture)
    thread = threading.Thread(target=responder.serve, daemon=True)
    thread.start()
    for _ in range(100):
        if servers:
            break
        threading.Event().wait(0.05)
    port = servers[0].server_address[1]

    def post(payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/alert",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 202
            return json.loads(resp.read())

    first = post(grafana_payload())
    second = post(grafana_payload())

    import http.client  # noqa: PLC0415

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)  # QA S5
    conn.putrequest("POST", "/alert")
    conn.putheader("Content-Length", "not-a-number")
    conn.endheaders()
    bad_length = conn.getresponse().status
    conn.close()
    responder.done.set()
    assert bad_length == 400
    thread.join(timeout=5)
    assert len(first["accepted"]) == 1 and second["accepted"] == []
    assert started == first["accepted"]
