"""Builds the summarizer chosen by `SUMMARIZER_PROVIDER` and exposes it as a dependency.

Auto rule (US-22 AC21): when `SUMMARIZER_PROVIDER` is empty, `gemini` if `GEMINI_API_KEY` is
set, otherwise `fake`. An explicit provider without its key fails at startup.
"""

from fastapi import Request

from app.config import Settings
from app.summarization.base import Summarizer
from app.summarization.fake import FakeSummarizer
from app.summarization.gemini import GeminiSummarizer
from app.summarization.groq import GroqSummarizer


class SummarizerConfigError(RuntimeError):
    """Invalid summary configuration; raised at startup so the app fails fast."""


def _has(secret_value: str) -> bool:
    return bool(secret_value.strip())


def resolve_provider(settings: Settings) -> str:
    if settings.summarizer_provider:
        return settings.summarizer_provider
    return "gemini" if _has(settings.gemini_api_key.get_secret_value()) else "fake"


def build_summarizer(settings: Settings) -> Summarizer:
    provider = resolve_provider(settings)
    if provider == "fake":
        return FakeSummarizer()
    if provider == "gemini":
        if not _has(settings.gemini_api_key.get_secret_value()):
            raise SummarizerConfigError(
                "GEMINI_API_KEY must be set when SUMMARIZER_PROVIDER=gemini "
                "(or leave SUMMARIZER_PROVIDER empty to use fake)"
            )
        return GeminiSummarizer(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
            timeout_seconds=settings.summary_timeout_seconds,
            primary_timeout_seconds=settings.gemini_primary_timeout_seconds,
        )
    if not _has(settings.groq_api_key.get_secret_value()):
        raise SummarizerConfigError(
            "GROQ_API_KEY must be set when SUMMARIZER_PROVIDER=groq "
            "(or leave SUMMARIZER_PROVIDER empty)"
        )
    return GroqSummarizer(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        model=settings.groq_summary_model,
        timeout_seconds=settings.summary_timeout_seconds,
    )


def get_summarizer(request: Request) -> Summarizer:
    """FastAPI dependency; tests override it with stubs via `app.dependency_overrides`."""
    summarizer: Summarizer = request.app.state.summarizer
    return summarizer
