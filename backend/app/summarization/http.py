"""Shared JSON POST for the HTTP summarizers (same httpx2 style as `app/transcription/groq.py`).

Privacy: logs and errors carry only the provider name, the HTTP status code and the exception
class. Never the API key, the request body (prompt, transcripts, images) or the response body.
"""

import logging
from typing import Any

import httpx2

from app.summarization.base import SummarizerError, SummarizerRateLimited, SummarizerTimeout

logger = logging.getLogger(__name__)

RATE_LIMITED_STATUS = 429


async def post_json(
    *,
    provider: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
    transport: httpx2.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """POST `payload`; return the JSON object or raise a safe `Summarizer*` error."""
    try:
        async with httpx2.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx2.TimeoutException:
        logger.warning("summary provider timed out", extra={"provider": provider})
        raise SummarizerTimeout(provider) from None
    except httpx2.HTTPError as exc:
        logger.warning(
            "summary provider unreachable",
            extra={"provider": provider, "error_type": type(exc).__name__},
        )
        raise SummarizerError(provider) from None
    return _parse(provider, response)


def _parse(provider: str, response: httpx2.Response) -> dict[str, Any]:
    if response.status_code == RATE_LIMITED_STATUS:
        logger.warning("summary provider rate limited", extra={"provider": provider})
        raise SummarizerRateLimited(provider)
    if not response.is_success:
        logger.warning(
            "summary provider error",
            extra={"provider": provider, "status_code": response.status_code},
        )
        raise SummarizerError(provider, response.status_code)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        logger.warning("summary provider sent invalid JSON", extra={"provider": provider})
        raise SummarizerError(provider, response.status_code)
    return payload


def invalid_response(provider: str) -> SummarizerError:
    logger.warning("summary provider returned no text", extra={"provider": provider})
    return SummarizerError(provider)
