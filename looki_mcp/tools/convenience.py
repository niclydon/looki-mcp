"""Convenience composite tools: recent_activity, todays_moments, moment_with_media, search_with_details.

Date semantics:
- All "today" / "N days ago" calculations use the user's configured timezone
  (LOOKI_USER_TIMEZONE env var, IANA name like "America/New_York"). When the
  variable is unset, calculations use UTC.
- Tool responses include BOTH `*_local` and `*_utc` date fields so consumers
  can see exactly what the server queried with and reason about boundaries.
- The Looki API itself returns moments tagged with their own per-moment `tz`
  field; this server does not transform those values.
"""

from __future__ import annotations

import asyncio
import json
import zoneinfo
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap
from looki_mcp.config import get_config


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _today_local() -> str:
    """Returns today's date in the configured user timezone, or UTC if unset."""
    tz_name = get_config().user_timezone
    if tz_name is None:
        return _today_utc()
    return datetime.now(zoneinfo.ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def _days_ago_local(days: int) -> str:
    """Returns the date N days ago in the configured user timezone, or UTC if unset."""
    tz_name = get_config().user_timezone
    if tz_name is None:
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    now_local = datetime.now(zoneinfo.ZoneInfo(tz_name))
    return (now_local - timedelta(days=days)).strftime("%Y-%m-%d")


def _date_envelope(local_field: str, utc_field: str) -> dict[str, str]:
    """Build a small descriptor: {local_field: <local>, utc_field: <utc>, timezone: <name>}."""
    tz = get_config().user_timezone
    return {
        local_field: _today_local() if "today" in local_field else _today_utc(),
        utc_field: _today_utc(),
        "timezone": tz or "UTC",
    }


def register_convenience_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_recent_activity(days: int = 7) -> str:
        """
        Returns a calendar summary for the last N days ending today. Uses the server's
        configured timezone (LOOKI_USER_TIMEZONE) for "today"; defaults to UTC if unset.
        Use for "what have I been up to lately?", "how active was I this week?", or any
        question about recent activity patterns without knowing specific dates.

        The response includes the date range it queried with under `period`, with both
        local (server-configured TZ) and UTC values so consumers can see exactly what
        boundary was used.

        Args:
            days: Number of days to look back. Between 1 and 90, default 7.
        """
        if not (1 <= days <= 90):
            return "Error: days must be between 1 and 90."
        tz = get_config().user_timezone or "UTC"
        end_date_local = _today_local()
        start_date_local = _days_ago_local(days)
        end_date_utc = _today_utc()
        start_date_utc = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d"
        )
        try:
            async with get_client() as client:
                response = await client.get(
                    "/moments/calendar",
                    params={"start_date": start_date_local, "end_date": end_date_local},
                )
                data = unwrap(response)
                payload = data if isinstance(data, dict) else {"data": data}
                return json.dumps(
                    {
                        "period": {
                            "days": days,
                            "timezone": tz,
                            "start_date_local": start_date_local,
                            "end_date_local": end_date_local,
                            "start_date_utc": start_date_utc,
                            "end_date_utc": end_date_utc,
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
        Returns all moments captured today. "Today" is computed in the server's
        configured timezone (LOOKI_USER_TIMEZONE), or UTC if that env var is unset.
        Use for "what did I do today?" or "show me today's memories".

        The response includes both `date_local` and `date_utc` so consumers can see
        which calendar day was queried.
        """
        tz = get_config().user_timezone or "UTC"
        date_local = _today_local()
        date_utc = _today_utc()
        try:
            async with get_client() as client:
                response = await client.get("/moments", params={"on_date": date_local})
                data = unwrap(response)
                payload = data if isinstance(data, dict) else {"data": data}
                return json.dumps(
                    {
                        "date_local": date_local,
                        "date_utc": date_utc,
                        "timezone": tz,
                        **payload,
                    },
                    indent=2,
                )
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

        Date arguments are passed through verbatim; this tool does not apply timezone
        conversion to user-supplied dates. Use whatever date the user gave you.

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
