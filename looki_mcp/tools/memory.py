"""Memory overview tool: get_memory_overview.

The memory overview is Looki's consolidated personal-context record: a
set of maintained summaries about the user (identity, lifestyle, traits,
interests, relationships, current experiences, and Looki response
preferences). It is a context summary, not an event timeline — for what
happened on a specific day use the moments / journals / summaries tools.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, governed_get, unwrap


def register_memory_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_memory_overview() -> str:
        """
        Returns the user's consolidated Looki memory overview: maintained
        summary sections covering identity, lifestyle, traits, interests,
        relationships, current experiences, and Looki response preferences,
        plus the `updated_at` timestamp of the overview.

        This is a consolidated context summary, not an event timeline. The
        summaries are returned in full; Looki content is never truncated in
        this server. Use it to ground answers in who the user is before
        drilling into moments, journals, or summaries for specifics.
        """
        try:
            async with get_client() as client:
                response = await governed_get(client, "/memory/overview")
                data = unwrap(response)
                return json.dumps(data, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
