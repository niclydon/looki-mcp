"""Realtime tool: get_realtime_event (beta)."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap


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
