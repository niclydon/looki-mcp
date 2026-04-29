"""Profile tool: get_profile."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client


def register_profile_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_profile() -> str:
        """
        Returns the authenticated user's Looki profile: first name, last name, email,
        timezone (tz field), region, birthday, and other account details. Use this to
        identify the user, get their timezone for accurate date calculations, or verify
        the connection is working correctly.
        """
        try:
            async with get_client() as client:
                response = await client.get("/me")
                response.raise_for_status()
                return json.dumps(response.json(), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
