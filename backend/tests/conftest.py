"""Shared pytest configuration for unit and integration tests."""

import asyncio
import os
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from app.config import get_settings
from app.db.session import get_engine, get_sessionmaker

TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"

# Env vars the backend reads; cleared per test so a developer's shell or .env never leaks in.
BACKEND_ENV_VARS = (
    "APP_ENV",
    "LOG_LEVEL",
    "DATABASE_URL",
    "TRANSCRIBER_PROVIDER",
    "GROQ_API_KEY",
    "GROQ_BASE_URL",
    "GROQ_MODEL",
    "TRANSCRIBE_TIMEOUT_SECONDS",
    "MAX_AUDIO_MB",
    "MAX_IMAGE_MB",
    "SUMMARIZER_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_BASE_URL",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODEL",
    "GROQ_SUMMARY_MODEL",
    "SUMMARY_TIMEOUT_SECONDS",
    "SUMMARY_MAX_CHARS",
    "SUMMARY_MAX_IMAGES",
    "SUMMARY_IMAGE_MAX_PX",
    "SUMMARY_MAX_IMAGE_BYTES",
    "STATIC_DIR",
    "RENDER_GIT_COMMIT",
    "GIT_SHA",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_SERVICE_NAME",
    "OTEL_METRIC_EXPORT_INTERVAL",
    "OTEL_SEMCONV_STABILITY_OPT_IN",
)
# `app.main` builds the app at import time: never let a developer's OTLP endpoint switch
# telemetry on (and start exporters) while the test modules are being imported (#29).
for _name in BACKEND_ENV_VARS:
    if _name.startswith("OTEL_"):
        os.environ.pop(_name, None)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(TEST_DATABASE_URL_ENV):
        return
    skip = pytest.mark.skip(
        reason=f"integration test: set {TEST_DATABASE_URL_ENV} (or run `make test`) to use Postgres"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, Any]]:
    # psycopg's async mode cannot use the Windows Proactor loop.
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio", {}


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in BACKEND_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRANSCRIBER_PROVIDER", "fake")
    _clear_caches()
    yield
    _clear_caches()


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
