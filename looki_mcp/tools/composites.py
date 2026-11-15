"""Composite context tools: get_day_context, get_personal_context.

These composites assemble the per-record tools into the two grains agents
actually ask for: one day, and the standing personal context. Every
section is labeled with its source record type, and a failing ingredient
surfaces as that section's `error` — it never fails the whole call.
All ingredient calls go through the governed client on one connection;
section content is returned in full (Looki content is never truncated).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP

from looki_mcp.audio_summary import normalize_moment_payload
from looki_mcp.client import format_error, get_client, governed_get, unwrap
from looki_mcp.tools.convenience import _today_local
from looki_mcp.tools.health import _fetch_health_reports
from looki_mcp.tools.journals import (
    _flatten_buckets,
    _journals_for_date,
    _shape_entry,
    normalize_date,
)
from looki_mcp.tools.summaries import _fetch_summaries


async def _section(source: str, make: Callable[[], Awaitable[Any]]) -> dict:
    """Runs one ingredient, isolating its failure to its own section."""
    try:
        return {"source": source, "data": await make()}
    except Exception as exc:
        return {"source": source, "error": format_error(exc)}


def _latest_item(items: list, key: str = "on_date") -> Any:
    """Picks the item with the greatest key value (ISO dates sort as text)."""
    dated = [i for i in items if isinstance(i, dict) and i.get(key)]
    if not dated:
        return None
    return max(dated, key=lambda i: str(i[key]))


def register_composite_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_day_context(date: str) -> str:
        """
        Returns everything Looki recorded about one date in a single call,
        as labeled sections by source record type:

        - moments: the day's moments at index level (id/title/time spine
          with normalized audio_summary), as in get_moments_by_date.
        - daily_summary: the day's life summary (summaries, type=daily).
        - health_report: the day's health report items (health-reports).
        - journals: the day's journal entries in summary mode, as in
          get_journals_by_date (bounded feed scan: at most 6 pages / 186
          feed days; `scan_capped` flags a date beyond the scan window).

        A section that fails upstream carries its own `error` instead of
        failing the whole call. Section content is in full.

        Args:
            date: The date, YYYY-MM-DD (unpadded month/day accepted).
        """
        normalized = normalize_date(date)
        if normalized is None:
            return "Error: date must be in YYYY-MM-DD format."
        date = normalized
        async with get_client() as client:

            async def moments_section() -> Any:
                response = await governed_get(client, "/moments", params={"on_date": date})
                data = unwrap(response)
                return normalize_moment_payload(data, summary=True)

            async def summary_section() -> Any:
                payload = await _fetch_summaries(client, date, date, "daily")
                return payload["items"]

            async def health_section() -> Any:
                payload = await _fetch_health_reports(client, date, date)
                return payload["items"]

            async def journals_section() -> Any:
                buckets, _pages, capped = await _journals_for_date(client, date)
                entries = _flatten_buckets(buckets)
                return {
                    "entry_count": len(entries),
                    "entries": [_shape_entry(e, "summary") for e in entries],
                    "scan_capped": capped,
                }

            sections = {
                "moments": await _section("moments", moments_section),
                "daily_summary": await _section("summaries:daily", summary_section),
                "health_report": await _section("health_reports", health_section),
                "journals": await _section("journals", journals_section),
            }
        return json.dumps({"date": date, "sections": sections}, indent=2)

    @mcp.tool
    async def get_personal_context() -> str:
        """
        Returns the user's standing Looki context in a single call, as
        labeled sections by source record type:

        - memory_overview: the consolidated context summary (identity,
          lifestyle, traits, interests, relationships, current
          experiences, Looki preferences) plus its updated_at.
        - latest_daily_summary: the most recent daily life summary in
          the last 7 days (or null when none exists in that window).
        - latest_weekly_summary: the most recent weekly life summary in
          the last 28 days (or null when none exists in that window).

        "Recent" windows end today in the server's configured timezone
        (LOOKI_USER_TIMEZONE, else UTC). A section that fails upstream
        carries its own `error` instead of failing the whole call.
        Section content is in full.
        """
        today = _today_local()
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        daily_start = (today_dt - timedelta(days=6)).strftime("%Y-%m-%d")
        weekly_start = (today_dt - timedelta(days=27)).strftime("%Y-%m-%d")
        async with get_client() as client:

            async def overview_section() -> Any:
                response = await governed_get(client, "/memory/overview")
                return unwrap(response)

            async def daily_section() -> Any:
                payload = await _fetch_summaries(client, daily_start, today, "daily")
                return _latest_item(payload["items"])

            async def weekly_section() -> Any:
                payload = await _fetch_summaries(client, weekly_start, today, "weekly")
                return _latest_item(payload["items"])

            sections = {
                "memory_overview": await _section("memory_overview", overview_section),
                "latest_daily_summary": await _section("summaries:daily", daily_section),
                "latest_weekly_summary": await _section("summaries:weekly", weekly_section),
            }
        return json.dumps({"as_of": today, "sections": sections}, indent=2)
