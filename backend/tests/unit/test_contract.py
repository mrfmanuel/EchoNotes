"""#23: `openapi.yaml` (the contract) and the FastAPI app describe the same API.

Only `/api/*` operations are compared, so FastAPI's docs routes (`/docs`, `/openapi.json`) and
the SPA catch-all (`include_in_schema=False`) are out of scope. Path parameter names are
normalized (`{projectId}` == `{project_id}`). Intentional difference (docs/testing.md):
FastAPI adds an automatic `422` to every operation with a path parameter (malformed UUID);
the contract documents `422` only where a request body or query can be invalid.
"""

import re
from pathlib import Path
from typing import Any

import httpx2
import pytest
import yaml

from app.config import get_settings
from app.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "openapi.yaml"
HTTP_METHODS = frozenset({"get", "put", "post", "patch", "delete", "head", "options", "trace"})
AUTOMATIC_VALIDATION_STATUS = "422"

Operation = tuple[str, str]  # (normalized path, METHOD)


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _operations(spec: dict[str, Any]) -> dict[Operation, dict[str, Any]]:
    return {
        (_normalize(path), method.upper()): operation
        for path, item in spec["paths"].items()
        if path.startswith("/api/") or path == "/api"
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


@pytest.fixture(scope="module")
def contract_ops() -> dict[Operation, dict[str, Any]]:
    return _operations(yaml.safe_load(CONTRACT.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def app_ops() -> dict[Operation, dict[str, Any]]:
    return _operations(create_app().openapi())


def _success_codes(operation: dict[str, Any]) -> set[str]:
    return {code for code in operation["responses"] if code.startswith("2")}


def test_app_and_contract_have_the_same_api_operations(
    contract_ops: dict[Operation, dict[str, Any]], app_ops: dict[Operation, dict[str, Any]]
) -> None:
    assert sorted(app_ops.keys() - contract_ops.keys()) == [], "in the app, missing in yaml"
    assert sorted(contract_ops.keys() - app_ops.keys()) == [], "in openapi.yaml, missing in app"
    assert len(app_ops) >= 18


def test_operation_ids_match_the_contract(
    contract_ops: dict[Operation, dict[str, Any]], app_ops: dict[Operation, dict[str, Any]]
) -> None:
    mismatched = {
        op: (app_ops[op].get("operationId"), contract_ops[op].get("operationId"))
        for op in app_ops.keys() & contract_ops.keys()
        if app_ops[op].get("operationId") != contract_ops[op].get("operationId")
    }
    assert mismatched == {}


def test_success_status_codes_match_the_contract(
    contract_ops: dict[Operation, dict[str, Any]], app_ops: dict[Operation, dict[str, Any]]
) -> None:
    mismatched = {
        op: (sorted(_success_codes(app_ops[op])), sorted(_success_codes(contract_ops[op])))
        for op in app_ops.keys() & contract_ops.keys()
        if _success_codes(app_ops[op]) != _success_codes(contract_ops[op])
    }
    assert mismatched == {}


def test_documented_error_codes_are_declared_by_the_app(
    contract_ops: dict[Operation, dict[str, Any]], app_ops: dict[Operation, dict[str, Any]]
) -> None:
    for op in app_ops.keys() & contract_ops.keys():
        app_codes, contract_codes = (
            set(app_ops[op]["responses"]),
            set(contract_ops[op]["responses"]),
        )
        assert contract_codes - app_codes == set(), f"{op}: documented but not declared"
        assert app_codes - contract_codes <= {AUTOMATIC_VALIDATION_STATUS}, f"{op}: undocumented"


def test_contract_test_detects_an_extra_operation(
    contract_ops: dict[Operation, dict[str, Any]],
) -> None:
    spec = {"paths": {"/api/extra/{id}": {"post": {"responses": {"201": {}}}}}}

    extra = _operations(spec).keys() - contract_ops.keys()

    assert extra == {("/api/extra/{}", "POST")}


# --- Health response body vs. the `Health` schema (#47, US-17 AC3) ------------------------------


def _schema_violations(body: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Validate a flat object of string properties (enough for `Health`; no new dependency)."""
    properties: dict[str, Any] = schema["properties"]
    problems = [f"missing {key}" for key in schema["required"] if key not in body]
    problems += [f"undocumented {key}" for key in body if key not in properties]
    for key, value in body.items():
        rule = properties.get(key, {})
        if rule.get("type") == "string" and not isinstance(value, str):
            problems.append(f"{key} is not a string")
        if "enum" in rule and value not in rule["enum"]:
            problems.append(f"{key}={value!r} not in {rule['enum']}")
    return problems


@pytest.fixture(scope="module")
def health_schema() -> dict[str, Any]:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return spec["components"]["schemas"]["Health"]


def test_health_schema_requires_commit_and_environment(health_schema: dict[str, Any]) -> None:
    required = set(health_schema["required"])

    assert {"status", "version", "database", "commit", "environment"} <= required
    assert health_schema["properties"]["commit"]["type"] == "string"
    assert health_schema["properties"]["environment"]["enum"] == ["local", "dev", "prod"]


@pytest.mark.anyio
@pytest.mark.parametrize("app_env", ["local", "dev", "prod"])
async def test_health_response_validates_against_the_contract_schema(
    client: httpx2.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    health_schema: dict[str, Any],
    app_env: str,
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("GIT_SHA", "0f1e2d3c4b5a69788796a5b4c3d2e1f0a9b8c7d6")
    get_settings.cache_clear()

    response = await client.get("/api/health")

    assert response.status_code == 200
    assert _schema_violations(response.json(), health_schema) == []


def test_schema_check_detects_a_missing_or_invalid_field(health_schema: dict[str, Any]) -> None:
    body = {"status": "ok", "version": "1.0.0", "database": "ok", "environment": "staging"}

    assert _schema_violations(body, health_schema) == [
        "missing commit",
        "environment='staging' not in ['local', 'dev', 'prod']",
    ]
