"""Groq text-only summarizer (OpenAI-compatible `POST {GROQ_BASE_URL}/chat/completions`).

It sends no image bytes: the prompt already lists each screenshot by number, filename and
linked transcript, so the model can still place `<figure data-screenshot="N">` (US-22 AC13).
"""

from typing import Any

import httpx2
from pydantic import SecretStr

from app.summarization.base import SummaryRequest, SummaryResult
from app.summarization.http import invalid_response, post_json

MAX_COMPLETION_TOKENS = 8192


def build_payload(model: str, request: SummaryRequest) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": request.system_instruction},
            {"role": "user", "content": request.user_text},
        ],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }


def extract_text(payload: dict[str, Any]) -> str | None:
    """`choices[0].message.content`; `None` when missing or blank."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) and content.strip() else None


class GroqSummarizer:
    name = "groq"

    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport  # tests inject an `httpx2.MockTransport`

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        response = await post_json(
            provider=self.name,
            url=self._url,
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
            payload=build_payload(self._model, request),
            timeout_seconds=self._timeout,
            transport=self._transport,
        )
        text = extract_text(response)
        if text is None:
            raise invalid_response(self.name)
        return SummaryResult(fragment=text, model=self._model)
