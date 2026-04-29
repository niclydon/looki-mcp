"""Profile tool: get_profile."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap


def register_profile_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_profile() -> str:
        """
        Returns the authenticated user's Looki profile: first name, last name, email,
        timezone (tz field, e.g. "-04:00"), region, birthday, and other account
        details. Use this to identify the user, get their timezone for accurate date
        calculations, or verify the connection is working correctly.
        """
        try:
            async with get_client() as client:
                response = await client.get("/me")
                data = unwrap(response)
                # Looki wraps profile in data.user; surface the user object directly.
                profile = data.get("user", data) if isinstance(data, dict) else data
                return json.dumps(profile, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
