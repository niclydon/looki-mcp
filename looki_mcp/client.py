"""Async httpx client factory, response unwrapping, and error formatting.

Tools use `async with get_client() as client:` to make requests. The factory
pulls credentials from the loaded Config and injects them as the X-API-Key
header. The API key is never logged or returned in tool responses.

Looki API responses are wrapped in a `{code, detail, data}` envelope. The
unwrap() helper extracts `data` on success and raises LookiApiError on
failure so tool error handling stays simple.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from looki_mcp.config import get_config
from looki_mcp.insight.governor import get_governor


class LookiApiError(Exception):
    """Raised when the Looki API returns a non-zero code in its response envelope."""

    def __init__(self, code: int, detail: str) -> None:
        super().__init__(f"Looki API error (code={code}): {detail}")
        self.code = code
        self.detail = detail


def get_client() -> httpx.AsyncClient:
    """Returns a configured httpx.AsyncClient. Use as an async context manager."""
    config = get_config()
    return httpx.AsyncClient(
        base_url=config.base_url,
        headers={
            "X-API-Key": config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30.0,
    )


def unwrap(response: httpx.Response) -> Any:
    """Validates HTTP status, then unwraps the Looki `{code, detail, data}` envelope.

    Returns the value of `data` on success.
    Raises httpx.HTTPStatusError on non-2xx responses.
    Raises LookiApiError when the body has a non-zero `code`.
    """
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        return body  # Defensive: API might one day return a bare value
    code = body.get("code", 0)
    if code != 0:
        detail = body.get("detail") or body.get("message") or "unknown error"
        raise LookiApiError(code, detail)
    return body.get("data", body)


def format_error(exc: Exception) -> str:
    """Returns a human-readable error string. Never includes the API key."""
    if isinstance(exc, LookiApiError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "Rate limit reached (60 requests/minute). Please wait before retrying."
        try:
            body = exc.response.json()
            detail = (
                body.get("detail")
                or body.get("message")
                or body.get("error")
                or exc.response.text
            )
        except Exception:
            detail = exc.response.text or str(exc)
        return f"Looki API error {status}: {detail}"
    if isinstance(exc, httpx.RequestError):
        return f"Network error: {exc}. Check your internet connection."
    return f"Unexpected error: {exc}"


_MAX_RETRY_AFTER_SECONDS = 30.0


async def governed_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 2,
) -> httpx.Response:
    """GET routed through the shared rate governor, with 429 Retry-After backoff.

    Raises httpx.HTTPStatusError if still 429 after max_retries (callers map it
    via format_error). Non-429 4xx/5xx raise immediately via raise_for_status().
    """
    governor = get_governor()
    attempt = 0
    while True:
        async with governor.slot():
            response = await client.get(url, params=params)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt >= max_retries:
            response.raise_for_status()  # raises HTTPStatusError(429)
        retry_after = response.headers.get("retry-after")
        try:
            delay = min(float(retry_after), _MAX_RETRY_AFTER_SECONDS) if retry_after else 1.0
        except ValueError:
            delay = 1.0
        await asyncio.sleep(delay)
        attempt += 1
