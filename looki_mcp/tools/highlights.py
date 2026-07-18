"""Highlights tool: get_highlights."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap

# Live Open API enum (2026-07): only these values are accepted on /for_you/items.
# Comic-like content appears as item `type`s under group=other, not as a group filter.
VALID_GROUPS = frozenset({"all", "vlog", "other"})
VALID_ORDER_BY = frozenset({"created_at", "recorded_at"})


def validate_highlights_group(group: str) -> str | None:
    """Return an Error string if group is invalid, else None."""
    if group not in VALID_GROUPS:
        return f"Error: group must be one of {sorted(VALID_GROUPS)}."
    return None


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
        Returns AI-generated highlight content created from captured memories — vlogs
        and other curated formats. Use when the user asks to see their highlights,
        creative content, or AI-generated summaries of their memories.

        Args:
            group: Filter by highlight group. One of: all, vlog, other. Default all.
                (Comic-style items may appear under group=other via their type field.)
            liked: If True, return only liked highlights. Omit for all.
            recorded_from: Filter to highlights recorded on or after this date (YYYY-MM-DD).
            recorded_to: Filter to highlights recorded on or before this date (YYYY-MM-DD).
            created_from: Filter to highlights created on or after this date (YYYY-MM-DD).
            created_to: Filter to highlights created on or before this date (YYYY-MM-DD).
            cursor_id: Pagination cursor from a previous response.
            limit: Number of highlights to return. Between 1 and 100, default 20.
            order_by: Sort field. One of: created_at, recorded_at. Default recorded_at.
        """
        group_err = validate_highlights_group(group)
        if group_err is not None:
            return group_err
        if order_by not in VALID_ORDER_BY:
            return f"Error: order_by must be one of {sorted(VALID_ORDER_BY)}."
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
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
