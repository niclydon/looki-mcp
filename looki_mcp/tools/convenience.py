"""Convenience composite tools: recent_activity, todays_moments, moment_with_media, search_with_details.

Note on dates: all "today" / "N days ago" calculations use UTC. The Looki API stores
moments with their own `tz` field per moment; this server does not localize requests
to the user's timezone. Tool docstrings make this explicit so the AI assistant can
warn the user when the boundary matters (e.g., near midnight local time).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap


def _today_utc() -> str:
    """Returns today's date in UTC as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago_utc(days: int) -> str:
    """Returns the date N days ago (UTC) as YYYY-MM-DD."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def register_convenience_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_recent_activity(days: int = 7) -> str:
        """
        Returns a calendar summary for the last N days ending today (UTC). Use for
        "what have I been up to lately?", "how active was I this week?", or any
        question about recent activity patterns without knowing specific dates.

        Note: dates are calculated in UTC. If the user is in a timezone where the
        current local date differs from UTC, results near midnight may include or
        exclude moments compared to what they'd expect locally. Use
        `get_moments_calendar` with explicit dates if exact local boundaries matter.

        Args:
            days: Number of days to look back. Between 1 and 90, default 7.
        """
        if not (1 <= days <= 90):
            return "Error: days must be between 1 and 90."
        end_date = _today_utc()
        start_date = _days_ago_utc(days)
        try:
            async with get_client() as client:
                response = await client.get(
                    "/moments/calendar",
                    params={"start_date": start_date, "end_date": end_date},
                )
                data = unwrap(response)
                payload = data if isinstance(data, dict) else {"data": data}
                return json.dumps(
                    {
                        "period": {
                            "start_date_utc": start_date,
                            "end_date_utc": end_date,
                            "days": days,
                        },
                        **payload,
                    },
                    indent=2,
                )
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_todays_moments() -> str:
        """
        Returns all moments captured today (UTC) — i.e. with a `date` of the current
        UTC calendar day. Use for "what did I do today?" or "show me today's memories".

        Note: this is UTC, not the user's local timezone. If the user wants strict
        local-day boundaries, use `get_moments_by_date` with their preferred YYYY-MM-DD.
        """
        date = _today_utc()
        try:
            async with get_client() as client:
                response = await client.get("/moments", params={"on_date": date})
                data = unwrap(response)
                payload = data if isinstance(data, dict) else {"data": data}
                return json.dumps({"date_utc": date, **payload}, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_moment_with_media(
        moment_id: str,
        highlight_only: bool = False,
        media_limit: int = 10,
    ) -> str:
        """
        Returns full moment details AND the first page of associated media files in a
        single call. More efficient than calling get_moment_details and get_moment_files
        separately. Use when the user wants to see or reference a specific memory
        including its photos and videos.

        Args:
            moment_id: UUID of the moment.
            highlight_only: If True, return only highlighted media files. Default False.
            media_limit: Number of media files to return. Between 1 and 20, default 10.
        """
        if not (1 <= media_limit <= 20):
            return "Error: media_limit must be between 1 and 20."
        try:
            file_params: dict[str, str | int | bool] = {"limit": media_limit}
            if highlight_only:
                file_params["highlight"] = True

            async with get_client() as client:
                moment_task = client.get(f"/moments/{moment_id}")
                files_task = client.get(f"/moments/{moment_id}/files", params=file_params)
                moment_resp, files_resp = await asyncio.gather(moment_task, files_task)
                moment_data = unwrap(moment_resp)
                files_data = unwrap(files_resp)

            return json.dumps(
                {"moment": moment_data, "media": files_data},
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def search_moments_with_details(
        query: str,
        start_date: str | None = None,
        end_date: str | None = None,
        max_results: int = 5,
    ) -> str:
        """
        Runs a natural language search and automatically fetches full details for each
        result in one call. Returns richer results than raw search. Use when the user
        wants to find AND read about memories in a single step.

        Args:
            query: Natural language description of what to find. Between 1 and 100 characters.
            start_date: Restrict search to on or after this date (YYYY-MM-DD). Optional.
            end_date: Restrict search to on or before this date (YYYY-MM-DD). Optional.
            max_results: Maximum number of results to enrich with full details. Between 1 and 10, default 5.
        """
        if not query or len(query) > 100:
            return "Error: query must be between 1 and 100 characters."
        if not (1 <= max_results <= 10):
            return "Error: max_results must be between 1 and 10."
        try:
            search_params: dict[str, str | int] = {
                "query": query,
                "page": 1,
                "page_size": max_results,
            }
            if start_date is not None:
                search_params["start_date"] = start_date
            if end_date is not None:
                search_params["end_date"] = end_date

            async with get_client() as client:
                search_resp = await client.get("/moments/search", params=search_params)
                search_data = unwrap(search_resp)
                moments = (
                    search_data.get("moments", []) if isinstance(search_data, dict) else []
                )
                moment_ids = [m["id"] for m in moments if isinstance(m, dict) and "id" in m]

                detail_tasks = [client.get(f"/moments/{mid}") for mid in moment_ids]
                detail_responses = await asyncio.gather(*detail_tasks, return_exceptions=True)

            detailed: list[dict] = []
            for i, resp in enumerate(detail_responses):
                if isinstance(resp, BaseException):
                    detailed.append(moments[i])
                else:
                    try:
                        detailed.append(unwrap(resp))
                    except Exception:
                        detailed.append(moments[i])

            total = (
                search_data.get("total", len(detailed))
                if isinstance(search_data, dict)
                else len(detailed)
            )
            return json.dumps(
                {"query": query, "total": total, "results": detailed},
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"
