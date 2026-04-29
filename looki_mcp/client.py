"""Async httpx client factory and error formatting.

Tools use `async with get_client() as client:` to make requests. The factory
pulls credentials from the loaded Config and injects them as the X-API-Key
header. The API key is never logged or returned in tool responses.
"""

from __future__ import annotations

import httpx

from looki_mcp.config import get_config


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


def format_error(exc: Exception) -> str:
    """Returns a human-readable error string. Never includes the API key."""
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
