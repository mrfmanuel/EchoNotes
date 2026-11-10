"""Application settings read from environment variables (see `.env.example`)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

DEFAULT_DATABASE_URL = "postgresql+psycopg://echonotes:echonotes@localhost:5432/echonotes"

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

    Variables used by other components (`POSTGRES_*`, `VITE_*`, `OTEL_*`) are ignored.
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
    # Built SPA (frontend/dist) served by FastAPI. Unset/empty = API only (dev, tests).
    static_dir: Path | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("static_dir", mode="before")
    @classmethod
    def _empty_static_dir_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        return normalize_database_url(value) if isinstance(value, str) else value

    @property
    def sqlalchemy_url(self) -> str:
        """The database URL for SQLAlchemy. Never log this value."""
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
