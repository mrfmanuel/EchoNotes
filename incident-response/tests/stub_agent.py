"""Stand-in for `claude -p` in the responder tests (ONCALL_AGENT_CMD). Never calls a model.

Reads the prompt on stdin (and checks it carries the evidence), edits files in the current
directory (the incident worktree) according to ONCALL_STUB_SCENARIO, and prints a
`--output-format json` style envelope.
"""

import json
import os
import sys
from pathlib import Path

FIX = '''def ratio(numerator: float, denominator: float) -> float:
    """numerator / denominator; 0.0 when the denominator is zero."""
    if not denominator:
        return 0.0
    return numerator / denominator
'''
TEST = """from app.calc import ratio


def test_ratio_of_zero_denominator_is_zero() -> None:
    assert ratio(1.0, 0.0) == 0.0
"""
APP = "backend/app/calc.py"
NEW_TEST = "backend/tests/unit/test_calc_zero.py"


def answer(files: list[str], action: str = "apply_fix", confidence: float = 0.9) -> dict:
    return {
        "root_cause": "backend/app/calc.py:2 divides by a zero denominator for empty clips.",
        "evidence_used": ["logs: ZeroDivisionError in app/calc.py line 2"],
        "files_changed": files,
        "tests_added": [f"{NEW_TEST}::test_ratio_of_zero_denominator_is_zero"],
        "confidence": confidence,
        "proposed_action": action,
        "summary": "Guard the ratio against a zero denominator so short clips no longer fail.",
    }


def write(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def main() -> None:
    prompt = sys.stdin.read()
    assert "Evidence packet" in prompt and "INC-" in prompt, "prompt is missing the evidence"
    leaked = [name for name in ("GROQ_API_KEY", "GH_TOKEN", "GITHUB_TOKEN") if name in os.environ]
    scenario = os.environ.get("ONCALL_STUB_SCENARIO", "good_fix")
    result: dict | str
    if scenario == "good_fix":
        write(APP, FIX)
        write(NEW_TEST, TEST)
        result = answer([APP, NEW_TEST])
    elif scenario == "denied_path":
        write(APP, FIX)
        write(NEW_TEST, TEST)
        write(".github/workflows/evil.yml", "on: push\n")
        result = answer([APP, NEW_TEST, ".github/workflows/evil.yml"])
    elif scenario == "too_many_lines":
        write(APP, FIX + "".join(f"# padding line {i}\n" for i in range(80)))
        write(NEW_TEST, TEST)
        result = answer([APP, NEW_TEST])
    elif scenario == "breaks_tests":  # a test that reproduces the bug, but no fix
        write(NEW_TEST, TEST)
        result = answer([NEW_TEST])
    elif scenario == "misreported_files":
        write(APP, FIX)
        write(NEW_TEST, TEST)
        result = answer([APP])
    elif scenario == "escalate":
        result = answer([], action="escalate", confidence=0.2)
    elif scenario == "low_confidence":
        write(APP, FIX)
        write(NEW_TEST, TEST)
        result = answer([APP, NEW_TEST], confidence=0.3)
    elif scenario == "invalid_json":
        result = "I fixed it, trust me."
    elif scenario == "schema_violation":
        write(APP, FIX)
        write(NEW_TEST, TEST)
        result = {**answer([APP, NEW_TEST]), "proposed_action": "deploy_to_prod"}
    else:
        raise SystemExit(f"unknown scenario {scenario}")
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 3,
        "total_cost_usd": 0.0,
        "modelUsage": {"stub-model": {}},
        "result": result if isinstance(result, str) else json.dumps(result),
        "leaked_env": leaked,
    }
    if isinstance(result, dict):
        envelope["structured_output"] = result
    print(json.dumps(envelope))


if __name__ == "__main__":
    main()
