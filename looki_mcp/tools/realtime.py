"""Realtime tools for current activity inspection."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap
from looki_mcp.insight import llm as insight_llm
from looki_mcp.insight.envelope import render


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


async def _describe_realtime_event_impl() -> str:
    try:
        async with get_client() as client:
            response = await client.get("/realtime/latest-event")
            payload = unwrap(response)
        image_url = _extract_image_url(payload)
        narrative = await insight_llm.describe_image(
            image_url, "Describe the most important real-world event or activity in this image in one concise sentence.",
        ) if image_url else None
        return render(
            {"event": payload, "image_url": image_url},
            narrative=narrative,
            meta={"vlm_used": narrative is not None},
        )
    except Exception as exc:
        return f"Error: {format_error(exc)}"


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
        description when a snapshot is available and a VLM provider is configured
        (set `LOOKI_LLM_PROVIDER`, or `FORGE_*` for back-compat).
        """
        return await _describe_realtime_event_impl()
