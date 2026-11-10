"""#35 JSON log format and LOG_LEVEL filtering."""

import logging
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.main import create_app
from tests.log_utils import parse_json_logs


def _logs(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return parse_json_logs(capsys.readouterr().out)


def test_log_line_is_one_json_object_with_required_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("app.test").info("hello")

    records = _logs(capsys)
    assert len(records) == 1
    record = records[0]
    assert {"timestamp", "level", "logger", "message", "request_id"} <= record.keys()
    assert record["level"] == "INFO"
    assert record["logger"] == "app.test"
    assert record["message"] == "hello"
    assert record["request_id"] is None
    assert datetime.fromisoformat(record["timestamp"]).utcoffset() == timedelta(0)


def test_uvicorn_loggers_use_the_json_handler_and_access_log_is_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("uvicorn.error").info("server started")
    logging.getLogger("uvicorn.access").info("GET / 200")

    assert [r["logger"] for r in _logs(capsys)] == ["uvicorn.error"]


def test_log_level_warning_drops_info_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    create_app()
    capsys.readouterr()

    logging.getLogger("app.test").info("quiet")
    logging.getLogger("app.test").warning("loud")

    assert [r["message"] for r in _logs(capsys)] == ["loud"]


def test_log_level_debug_emits_debug_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    create_app()
    capsys.readouterr()

    logging.getLogger("app.test").debug("details")

    assert [r["level"] for r in _logs(capsys)] == ["DEBUG"]


def test_default_log_level_is_info(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()
    capsys.readouterr()

    logging.getLogger("app.test").debug("hidden")
    logging.getLogger("app.test").info("shown")

    assert [r["message"] for r in _logs(capsys)] == ["shown"]


def test_exception_log_has_class_and_stack_but_not_the_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_app()
    capsys.readouterr()

    user_title = "SECRET-" + "TITLE-123"  # user content only exists at runtime
    try:
        raise ValueError(user_title)
    except ValueError:
        logging.getLogger("app.test").exception("failed")

    output = capsys.readouterr().out
    assert "SECRET-TITLE-123" not in output
    (record,) = parse_json_logs(output)
    assert record["exc_type"] == "ValueError"
    assert "test_exception_log_has_class_and_stack" in record["stack_trace"]
