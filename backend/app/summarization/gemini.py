"""Google Gemini summarizer: REST `models/{model}:generateContent`, text + inline images.

On HTTP 429 (quota), 500 or 503 (overloaded / unavailable) from the primary model it retries
once with the fallback model (Flash-Lite, US-22 AC19). Any other status (402 billing and the
other 4xx included) and connection errors fail without a fallback.
`temperature` is deliberately not sent (Gemini 3.6+ ignores it and will reject it).
"""

import base64
from typing import Any

import httpx2
from pydantic import SecretStr

from app.summarization.base import (
    SummarizerError,
    SummaryRequest,
    SummaryResult,
)
from app.summarization.http import invalid_response, post_json

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


class GeminiSummarizer:
    name = "gemini"

    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        model: str,
        fallback_model: str,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._fallback_model = fallback_model.strip()
        self._timeout = timeout_seconds
        self._transport = transport  # tests inject an `httpx2.MockTransport`

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        payload = build_payload(request)
        try:
            return await self._generate(self._model, payload)
        except SummarizerError as exc:
            if not self._should_fall_back(exc):
                raise
            return await self._generate(self._fallback_model, payload)

    def _should_fall_back(self, exc: SummarizerError) -> bool:
        has_fallback = bool(self._fallback_model) and self._fallback_model != self._model
        return has_fallback and exc.status_code in FALLBACK_STATUSES

    async def _generate(self, model: str, payload: dict[str, Any]) -> SummaryResult:
        response = await post_json(
            provider=self.name,
            url=f"{self._base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": self._api_key.get_secret_value()},
            payload=payload,
            timeout_seconds=self._timeout,
            transport=self._transport,
        )
        text = extract_text(response)
        if text is None:
            raise invalid_response(self.name)
        return SummaryResult(fragment=text, model=model)
