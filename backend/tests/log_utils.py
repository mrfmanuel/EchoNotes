"""Helpers to read the JSON log lines the app writes to stdout."""

import json
from typing import Any


def parse_json_logs(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def access_lines(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["logger"] == "app.access"]
