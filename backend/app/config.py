"""Application settings read from environment variables (see `.env.example`)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
# Empty = auto: `gemini` when GEMINI_API_KEY is set, otherwise `fake` (US-22 AC21).
SummarizerProvider = Literal["", "gemini", "groq", "fake"]

DEFAULT_DATABASE_URL = "postgresql+psycopg://echonotes:echonotes@localhost:5432/echonotes"

UNKNOWN_COMMIT = "unknown"
DEFAULT_OTEL_SERVICE_NAME = "echonotes-api"

_URL_PREFIXES = ("postgres://", "postgresql://")
_PSYCOPG_PREFIX = "postgresql+psycopg://"


def normalize_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain Postgres URLs (Render gives `postgres://...`)."""
    for prefix in _URL_PREFIXES:
        if url.startswith(prefix):
            return _PSYCOPG_PREFIX + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    """Backend configuration. Only process environment variables are read (12-factor).

    Variables used by other components (`POSTGRES_*`, `VITE_*`) are ignored. Of the `OTEL_*`
    variables only the ones below are read here; the OTLP exporters read the rest themselves
    (e.g. `OTEL_EXPORTER_OTLP_HEADERS`, which may hold a credential and is never logged).
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_env: Literal["local", "dev", "prod"] = "local"
    log_level: LogLevel = "INFO"
    database_url: SecretStr = SecretStr(DEFAULT_DATABASE_URL)
    transcriber_provider: Literal["fake", "groq"] = "fake"
    groq_api_key: SecretStr = SecretStr("")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "whisper-large-v3-turbo"
    transcribe_timeout_seconds: float = Field(default=120, gt=0)
    max_audio_mb: int = Field(default=25, gt=0)
    max_image_mb: int = Field(default=5, gt=0)
    # AI project summary (US-22). Safe defaults: no new variable is required anywhere.
    summarizer_provider: SummarizerProvider = ""
    gemini_api_key: SecretStr = SecretStr("")
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"  # empty = no fallback on 429
    groq_summary_model: str = "openai/gpt-oss-120b"
    summary_timeout_seconds: float = Field(default=90, gt=0)  # the whole job, fallback included
    summary_max_chars: int = Field(default=60000, gt=0)  # total across all transcripts
    summary_max_images: int = Field(default=8, ge=0)
    summary_image_max_px: int = Field(default=1280, gt=0)  # longest side after downscaling
    # Built SPA (frontend/dist) served by FastAPI. Unset/empty = API only (dev, tests).
    static_dir: Path | None = None
    # Deployed commit (US-17 AC3): set by Render at runtime, or by the Docker `GIT_SHA` build arg.
    render_git_commit: str = ""
    git_sha: str = ""
    # OpenTelemetry (#29). Empty endpoint = telemetry fully off (no SDK, no exporters).
    # OTLP over http/protobuf, e.g. `http://lgtm:4318`; `/v1/traces` etc. are appended.
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = DEFAULT_OTEL_SERVICE_NAME
    otel_metric_export_interval: int = Field(default=5000, gt=0)  # milliseconds

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("summarizer_provider", mode="before")
    @classmethod
    def _normalize_summarizer_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("static_dir", mode="before")
    @classmethod
    def _empty_static_dir_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("otel_service_name", mode="before")
    @classmethod
    def _empty_service_name_is_default(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or DEFAULT_OTEL_SERVICE_NAME
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        return normalize_database_url(value) if isinstance(value, str) else value

    @property
    def telemetry_enabled(self) -> bool:
        return bool(self.otel_exporter_otlp_endpoint.strip())

    @property
    def deployed_commit(self) -> str:
        """`RENDER_GIT_COMMIT`, else `GIT_SHA`, else `"unknown"` (empty values count as unset)."""
        for value in (self.render_git_commit, self.git_sha):
            if value.strip():
                return value.strip()
        return UNKNOWN_COMMIT

    @property
    def sqlalchemy_url(self) -> str:
        """The database URL for SQLAlchemy. Never log this value."""
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
