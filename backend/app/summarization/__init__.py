"""Pluggable AI project summary (US-22, docs/architecture.md).

`SUMMARIZER_PROVIDER` selects `gemini` (multimodal), `groq` (text only) or `fake`
(deterministic, offline); empty = `gemini` when `GEMINI_API_KEY` is set, otherwise `fake`.
"""

from app.summarization.base import (
    Summarizer,
    SummarizerError,
    SummarizerRateLimited,
    SummarizerTimeout,
    SummaryImage,
    SummaryRequest,
    SummaryResult,
)
from app.summarization.factory import (
    SummarizerConfigError,
    build_summarizer,
    get_summarizer,
    resolve_provider,
)

__all__ = [
    "Summarizer",
    "SummarizerConfigError",
    "SummarizerError",
    "SummarizerRateLimited",
    "SummarizerTimeout",
    "SummaryImage",
    "SummaryRequest",
    "SummaryResult",
    "build_summarizer",
    "get_summarizer",
    "resolve_provider",
]
