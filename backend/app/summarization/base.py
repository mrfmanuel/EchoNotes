"""The `Summarizer` protocol, its request/result types and provider errors (US-22).

Privacy: errors carry only the provider name and the HTTP status code, never the API key,
the prompt, the transcripts, the images or any response text.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SummaryImage:
    """A downscaled screenshot sent to the model as image `n` (1-based)."""

    n: int
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class SummaryRequest:
    """Everything a provider needs. `user_text` already lists the images by number."""

    system_instruction: str
    user_text: str
    images: list[SummaryImage] = field(default_factory=list)
    # Only the deterministic `fake` provider reads these (it echoes the transcripts).
    transcript_titles: list[str] = field(default_factory=list)
    transcript_texts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SummaryResult:
    fragment: str  # untrusted HTML fragment; always sanitized before it is stored
    model: str  # the model that actually produced it (the fallback when used)


class Summarizer(Protocol):
    name: str

    async def summarize(self, request: SummaryRequest) -> SummaryResult: ...


class SummarizerError(Exception):
    """The provider failed (non-2xx, connection error, malformed or empty response)."""

    def __init__(self, provider: str, status_code: int | None = None) -> None:
        self.provider = provider
        self.status_code = status_code
        suffix = f" (status {status_code})" if status_code is not None else ""
        super().__init__(f"{provider} summary failed{suffix}")


class SummarizerRateLimited(SummarizerError):
    """HTTP 429 (quota / rate limit). Gemini retries once with the fallback model."""

    def __init__(self, provider: str) -> None:
        super().__init__(provider, 429)


class SummarizerTimeout(Exception):
    """The provider did not answer in time."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"{provider} summary timed out")
