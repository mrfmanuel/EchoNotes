"""Google Gemini summarizer: REST `models/{model}:generateContent`, text + inline images.

The primary model gets `GEMINI_PRIMARY_TIMEOUT_SECONDS`. When it times out, has a connection or
transport error, or answers HTTP 429 (quota), 500 or 503 (overloaded / unavailable), one
attempt is made with the fallback model (Flash-Lite, US-22 AC19) using the rest of the
`SUMMARY_TIMEOUT_SECONDS` budget. Other statuses (402 billing and the other 4xx) and empty or
invalid responses fail without a fallback.
`temperature` is deliberately not sent (Gemini 3.6+ ignores it and will reject it).
"""

import asyncio
import base64
import logging
from typing import Any

import httpx2
from pydantic import SecretStr

from app.summarization.base import (
    SummarizerError,
    SummarizerTimeout,
    SummarizerUnavailable,
    SummaryRequest,
    SummaryResult,
)
from app.summarization.http import invalid_response, post_json

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 8192
FALLBACK_STATUSES = frozenset({429, 500, 503})  # quota, internal error, overloaded


def build_payload(request: SummaryRequest) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": request.user_text}]
    for image in request.images:
        parts.append({"text": f"Screenshot {image.n}:"})
        parts.append(
            {
                "inline_data": {
                    "mime_type": image.mime_type,
                    "data": base64.b64encode(image.data).decode("ascii"),
                }
            }
        )
    return {
        "system_instruction": {"parts": [{"text": request.system_instruction}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
    }


def extract_text(payload: dict[str, Any]) -> str | None:
    """`candidates[0].content.parts[*].text` joined; `None` if there is no text at all."""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return None
    content = candidates[0].get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None
    texts = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    text = "".join(texts)
    return text if text.strip() else None


def effective_primary_timeout(primary_seconds: float, total_seconds: float) -> float:
    """The primary attempt must leave budget for the fallback: if it is not below the whole
    budget it is clamped to half of it."""
    return primary_seconds if primary_seconds < total_seconds else total_seconds / 2


class GeminiSummarizer:
    name = "gemini"

    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        model: str,
        fallback_model: str,
        timeout_seconds: float,
        primary_timeout_seconds: float | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._fallback_model = fallback_model.strip()
        self._timeout = timeout_seconds  # both attempts together
        self._has_fallback = bool(self._fallback_model) and self._fallback_model != model
        # Without a fallback the primary model may use the whole budget.
        self._primary_timeout = (
            effective_primary_timeout(primary_timeout_seconds or timeout_seconds, timeout_seconds)
            if self._has_fallback
            else timeout_seconds
        )
        self._transport = transport  # tests inject an `httpx2.MockTransport`

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        payload = build_payload(request)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        try:
            return await self._generate(self._model, payload, self._primary_timeout)
        except (SummarizerError, SummarizerTimeout) as exc:
            if not self._should_fall_back(exc):
                raise
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise SummarizerTimeout(self.name)
        logger.warning(
            "summary primary model failed, trying fallback", extra={"provider": self.name}
        )
        return await self._generate(self._fallback_model, payload, remaining)

    def _should_fall_back(self, exc: SummarizerError | SummarizerTimeout) -> bool:
        if not self._has_fallback:
            return False
        if isinstance(exc, SummarizerTimeout | SummarizerUnavailable):
            return True
        return exc.status_code in FALLBACK_STATUSES

    async def _generate(
        self, model: str, payload: dict[str, Any], timeout_seconds: float
    ) -> SummaryResult:
        """One attempt, bounded end to end (httpx's timeouts are per read, not per request)."""
        try:
            async with asyncio.timeout(timeout_seconds):
                response = await post_json(
                    provider=self.name,
                    url=f"{self._base_url}/models/{model}:generateContent",
                    headers={"x-goog-api-key": self._api_key.get_secret_value()},
                    payload=payload,
                    timeout_seconds=timeout_seconds,
                    transport=self._transport,
                )
        except TimeoutError:
            logger.warning("summary provider timed out", extra={"provider": self.name})
            raise SummarizerTimeout(self.name) from None
        text = extract_text(response)
        if text is None:
            raise invalid_response(self.name)
        return SummaryResult(fragment=text, model=model)
