"""Convenience composite tools: recent_activity, todays_moments, moment_with_media, search_with_details."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client


def _today_str(tz_name: str | None = None) -> str:
    """Returns today's date as YYYY-MM-DD, in the given timezone if provided."""
    if tz_name:
        try:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(tz_name)
            return datetime.now(tz).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago_str(days: int) -> str:
    """Returns the date N days ago as YYYY-MM-DD (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def register_convenience_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_recent_activity(days: int = 7) -> str:
        """
        Returns a calendar summary for the last N days ending today. Use for "what have
        I been up to lately?", "how active was I this week?", or any question about
        recent activity patterns without knowing specific dates.

        Args:
            days: Number of days to look back. Between 1 and 90, default 7.
        """
        if not (1 <= days <= 90):
            return "Error: days must be between 1 and 90."
        end_date = _today_str()
        start_date = _days_ago_str(days)
        try:
            async with get_client() as client:
                response = await client.get(
                    "/moments/calendar",
                    params={"start_date": start_date, "end_date": end_date},
                )
                response.raise_for_status()
                data = response.json()
                return json.dumps(
                    {
                        "period": {"start_date": start_date, "end_date": end_date, "days": days},
                        **data,
                    },
                    indent=2,
                )
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_todays_moments() -> str:
        """
        Returns all moments captured today in the user's local timezone. Use for "what
        did I do today?" or "show me today's memories". Automatically fetches the user's
        timezone from their profile for accurate date calculation.
        """
        try:
            tz_name: str | None = None
            try:
                async with get_client() as client:
                    profile_resp = await client.get("/me")
                    profile_resp.raise_for_status()
                    tz_name = profile_resp.json().get("tz")
            except Exception:
                pass  # Fall back to UTC if profile fetch fails

            date = _today_str(tz_name)
            async with get_client() as client:
                response = await client.get("/moments", params={"on_date": date})
                response.raise_for_status()
                data = response.json()
                return json.dumps({"date": date, **data}, indent=2)
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
                moment_resp.raise_for_status()
                files_resp.raise_for_status()

            return json.dumps(
                {"moment": moment_resp.json(), "media": files_resp.json()},
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
                search_resp.raise_for_status()
                search_data = search_resp.json()
                moments = search_data.get("moments", [])
                moment_ids = [m["id"] for m in moments]

                detail_tasks = [client.get(f"/moments/{mid}") for mid in moment_ids]
                detail_responses = await asyncio.gather(*detail_tasks, return_exceptions=True)

            detailed: list[dict] = []
            for i, resp in enumerate(detail_responses):
                if isinstance(resp, BaseException):
                    detailed.append(moments[i])
                else:
                    try:
                        resp.raise_for_status()
                        detailed.append(resp.json())
                    except Exception:
                        detailed.append(moments[i])

            return json.dumps(
                {
                    "query": query,
                    "total": search_data.get("total", len(detailed)),
                    "results": detailed,
                },
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"
