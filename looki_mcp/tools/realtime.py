"""Realtime tools for current activity inspection."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap

_langfuse_client: Any | None | bool = False


def _get_langfuse() -> Any | None:
    global _langfuse_client
    if os.environ.get("LANGFUSE_ENABLED") != "true":
        return None
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    if _langfuse_client is not False:
        return _langfuse_client
    try:
        from langfuse import Langfuse  # type: ignore

        kwargs = {
            "public_key": os.environ["LANGFUSE_PUBLIC_KEY"],
            "secret_key": os.environ["LANGFUSE_SECRET_KEY"],
        }
        if os.environ.get("LANGFUSE_BASE_URL"):
            kwargs["host"] = os.environ["LANGFUSE_BASE_URL"]
        _langfuse_client = Langfuse(**kwargs)
    except Exception:
        _langfuse_client = None
    return _langfuse_client


async def _forge_describe_image(image_url: str) -> str | None:
    forge_url = os.environ.get("FORGE_URL", "").strip()
    forge_api_key = os.environ.get("FORGE_API_KEY", "").strip()
    if not forge_url:
        return None

    headers = {"content-type": "application/json"}
    if forge_api_key:
        headers["authorization"] = f"Bearer {forge_api_key}"

    payload: dict[str, Any] = {
        "model": os.environ.get("FORGE_VLM_MODEL", "openai/gpt-4.1-mini"),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe the most important real-world event or activity in this image in one concise sentence."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "max_tokens": 80,
    }

    lf = _get_langfuse()
    trace = lf.trace(
        name="looki-mcp.realtime.describe",
        input={"image_url_chars": len(image_url)},
        metadata={"provider": "forge", "model": payload["model"]},
    ) if lf is not None else None
    generation = trace.generation(
        name="looki-mcp.realtime.describe",
        model=str(payload["model"]),
        input={"image_url_chars": len(image_url)},
    ) if trace is not None else None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{forge_url.rstrip('/')}/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        generation.end(output={"status": response.status_code}) if generation is not None else None
        trace.update(output={"status": response.status_code}) if trace is not None else None
        lf.flush() if lf is not None else None
    except Exception as exc:
        generation.end(level="ERROR", status_message=str(exc)) if generation is not None else None
        lf.flush() if lf is not None else None
        raise
    return (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content")
    )


def _extract_image_url(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("temporary_image_url", "image_url", "snapshot_url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    file_obj = payload.get("file")
    if isinstance(file_obj, dict):
        for key in ("temporary_url", "url"):
            value = file_obj.get(key)
            if isinstance(value, str) and value:
                return value
    latest_file = payload.get("latest_file")
    if isinstance(latest_file, dict):
        for key in ("temporary_url", "url"):
            value = latest_file.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def register_realtime_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_realtime_event() -> str:
        """
        Returns the most recent real-time event detected by the Looki device — what the
        user is currently doing or most recently did. Requires Proactive Mode to be
        enabled in the Looki app. Currently in beta. Use when the user asks "what am I
        doing right now?" or "what just happened?".
        """
        try:
            async with get_client() as client:
                response = await client.get("/realtime/latest-event")
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def describe_realtime_event() -> str:
        """
        Returns the latest realtime event plus an optional one-sentence visual
        description when a snapshot is available and Forge is configured.
        """
        try:
            async with get_client() as client:
                response = await client.get("/realtime/latest-event")
                payload = unwrap(response)
            image_url = _extract_image_url(payload)
            description = None
            if image_url:
                try:
                    description = await _forge_describe_image(image_url)
                except Exception:
                    description = None
            return json.dumps(
                {
                    "event": payload,
                    "image_url": image_url,
                    "description": description,
                },
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"
