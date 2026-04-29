"""Moments tools: calendar, by_date, details, files, search."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap


def register_moments_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_moments_calendar(start_date: str, end_date: str) -> str:
        """
        Returns a calendar view showing which days have recorded moments within a date
        range, with a highlight moment per day. Good for understanding activity density
        over a period, building timelines, or answering "what days was I active?" questions.

        Args:
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
        """
        try:
            async with get_client() as client:
                response = await client.get(
                    "/moments/calendar",
                    params={"start_date": start_date, "end_date": end_date},
                )
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_moments_by_date(date: str) -> str:
        """
        Returns all moments captured on a specific date, with titles, descriptions,
        time ranges, and cover images. Use when the user asks about a specific day or
        wants to review what happened on a particular date.

        Args:
            date: The date to retrieve moments for, in YYYY-MM-DD format.
        """
        try:
            async with get_client() as client:
                response = await client.get("/moments", params={"on_date": date})
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_moment_details(moment_id: str) -> str:
        """
        Returns full details for a single moment by its UUID, including title,
        description, start/end time, timezone, and media metadata. Use after finding a
        moment ID from search or calendar results to get its complete information.

        Args:
            moment_id: UUID of the moment to retrieve.
        """
        try:
            async with get_client() as client:
                response = await client.get(f"/moments/{moment_id}")
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_moment_files(
        moment_id: str,
        highlight: bool | None = None,
        cursor_id: str | None = None,
        limit: int = 20,
    ) -> str:
        """
        Returns photos and videos from a specific moment with pagination. Each file
        includes a temporary URL (valid 1 hour), media type (photo/video), size, and
        optional duration. Use when the user wants to view or reference specific media
        from a memory.

        Args:
            moment_id: UUID of the moment.
            highlight: If True, return only highlighted files. Omit for all files.
            cursor_id: Pagination cursor from a previous response for fetching the next page.
            limit: Number of files to return. Between 1 and 100, default 20.
        """
        if not (1 <= limit <= 100):
            return "Error: limit must be between 1 and 100."
        try:
            params: dict[str, str | int | bool] = {"limit": limit}
            if highlight is not None:
                params["highlight"] = highlight
            if cursor_id is not None:
                params["cursor_id"] = cursor_id
            async with get_client() as client:
                response = await client.get(f"/moments/{moment_id}/files", params=params)
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def search_moments(
        query: str,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> str:
        """
        Natural language search across all captured memories. Returns moments ranked by
        relevance. Use this when the user remembers something but not the exact date —
        e.g., "when did I go to the coffee shop?" or "find the moment where I was cooking
        pasta". More powerful than browsing by date.

        Args:
            query: Natural language description of what to find. Between 1 and 100 characters.
            start_date: Restrict search to on or after this date (YYYY-MM-DD). Optional.
            end_date: Restrict search to on or before this date (YYYY-MM-DD). Optional.
            page: Page number for pagination, starting at 1. Default 1.
            page_size: Number of results per page. Between 1 and 100, default 10.
        """
        if not query or len(query) > 100:
            return "Error: query must be between 1 and 100 characters."
        if not (1 <= page_size <= 100):
            return "Error: page_size must be between 1 and 100."
        try:
            params: dict[str, str | int] = {
                "query": query,
                "page": page,
                "page_size": page_size,
            }
            if start_date is not None:
                params["start_date"] = start_date
            if end_date is not None:
                params["end_date"] = end_date
            async with get_client() as client:
                response = await client.get("/moments/search", params=params)
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
