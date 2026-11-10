"""#9 settings acceptance criteria."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings, normalize_database_url
from app.main import create_app

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
BACKEND_KEYS = {
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
    "STATIC_DIR",
    "RENDER_GIT_COMMIT",
    "GIT_SHA",
}
# Documented in .env.example as comments, not values (#47): RENDER_GIT_COMMIT is set by Render,
# and a `GIT_SHA=` line copied into .env (compose env_file) would blank the image's baked GIT_SHA.
COMMENTED_KEYS = {"RENDER_GIT_COMMIT", "GIT_SHA"}


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_env_example_lists_every_backend_setting() -> None:
    assert _env_example_values().keys() >= BACKEND_KEYS - COMMENTED_KEYS
    assert all(key in ENV_EXAMPLE.read_text(encoding="utf-8") for key in COMMENTED_KEYS)
    assert {name.upper() for name in Settings.model_fields} == BACKEND_KEYS


def test_env_example_does_not_set_commit_values() -> None:
    """An uncommented GIT_SHA/RENDER_GIT_COMMIT in a copied .env would hide the real commit."""
    assert _env_example_values().keys() & COMMENTED_KEYS == set()
    assert "# GIT_SHA=" in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_settings_defaults_equal_env_example_values(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = Settings()
    for key, value in _env_example_values().items():
        monkeypatch.setenv(key, value)

    from_example = Settings()

    assert from_example == defaults
    assert defaults.transcriber_provider == "fake"
    assert defaults.log_level == "INFO"


def test_settings_ignore_compose_frontend_and_otel_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_USER", "someone")
    monkeypatch.setenv("VITE_API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    assert Settings().app_env == "local"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TRANSCRIBER_PROVIDER", "foo"),
        ("MAX_AUDIO_MB", "abc"),
        ("MAX_IMAGE_MB", "0"),
        ("APP_ENV", "staging"),
        ("LOG_LEVEL", "LOUD"),
        ("TRANSCRIBE_TIMEOUT_SECONDS", "-1"),
    ],
)
def test_invalid_setting_fails_app_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        create_app()


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert Settings().log_level == "DEBUG"


def test_repr_hides_groq_api_key_and_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_TOPSECRETKEY")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:PaSsW0rd-xyz@db.example:5432/app")

    settings = Settings()

    for text in (repr(settings), str(settings), str(settings.model_dump())):
        assert "gsk_TOPSECRETKEY" not in text
        assert "PaSsW0rd-xyz" not in text
    assert settings.groq_api_key.get_secret_value() == "gsk_TOPSECRETKEY"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
    ],
)
def test_database_url_is_normalized_to_psycopg(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", raw)

    assert normalize_database_url(raw) == expected
    assert Settings().sqlalchemy_url == expected
