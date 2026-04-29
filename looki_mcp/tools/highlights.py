"""Highlights tool: get_highlights."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client


def register_highlights_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_highlights(
        group: str = "all",
        liked: bool | None = None,
        recorded_from: str | None = None,
        recorded_to: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        cursor_id: str | None = None,
        limit: int = 20,
        order_by: str = "recorded_at",
    ) -> str:
        """
        Returns AI-generated highlight content created from captured memories — comics,
        vlogs, and other curated formats. Use when the user asks to see their highlights,
        creative content, or AI-generated summaries of their memories.

        Args:
            group: Filter by highlight type. One of: all, comic, vlog, present, other. Default all.
            liked: If True, return only liked highlights. Omit for all.
            recorded_from: Filter to highlights recorded on or after this date (YYYY-MM-DD).
            recorded_to: Filter to highlights recorded on or before this date (YYYY-MM-DD).
            created_from: Filter to highlights created on or after this date (YYYY-MM-DD).
            created_to: Filter to highlights created on or before this date (YYYY-MM-DD).
            cursor_id: Pagination cursor from a previous response.
            limit: Number of highlights to return. Between 1 and 100, default 20.
            order_by: Sort field. One of: created_at, recorded_at. Default recorded_at.
        """
        valid_groups = {"all", "comic", "vlog", "present", "other"}
        if group not in valid_groups:
            return f"Error: group must be one of {sorted(valid_groups)}."
        valid_order = {"created_at", "recorded_at"}
        if order_by not in valid_order:
            return f"Error: order_by must be one of {sorted(valid_order)}."
        if not (1 <= limit <= 100):
            return "Error: limit must be between 1 and 100."
        try:
            params: dict[str, str | int | bool] = {"limit": limit, "order_by": order_by}
            if group != "all":
                params["group"] = group
            if liked is not None:
                params["liked"] = liked
            if recorded_from is not None:
                params["recorded_from"] = recorded_from
            if recorded_to is not None:
                params["recorded_to"] = recorded_to
            if created_from is not None:
                params["created_from"] = created_from
            if created_to is not None:
                params["created_to"] = created_to
            if cursor_id is not None:
                params["cursor_id"] = cursor_id
            async with get_client() as client:
                response = await client.get("/for_you/items", params=params)
                response.raise_for_status()
                return json.dumps(response.json(), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
