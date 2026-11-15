"""Health reports tool: get_health_reports.

Health reports are Looki's own daily health-related observations and
estimates (diet, activity metrics, sleep-adjacent signals) — they are
Looki-generated estimates, to be presented as such, not as medical facts.

Upstream range contract (verified live 2026-11-09): the endpoint silently
truncates long ranges — a 68-day request returned only the first 30 days
of items, with no error. This tool therefore pages ranges as adjacent
non-overlapping 30-day windows and merges the items. The required query
params are exactly `start_date` / `end_date` (the plural route
/health-reports; /health and /health/reports are 404).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, governed_get, unwrap

# Longest window verified to return complete results (2026-11-09): wider
# requests silently return only the first 30 days of the range.
_RANGE_WINDOW_DAYS = 30


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    """Splits [start, end] into adjacent non-overlapping <=30-day windows."""
    out: list[tuple[str, str]] = []
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=_RANGE_WINDOW_DAYS - 1), end)
        out.append((cur.strftime("%Y-%m-%d"), win_end.strftime("%Y-%m-%d")))
        cur = win_end + timedelta(days=1)
    return out


async def _fetch_health_reports(client, start_date: str, end_date: str) -> dict:
    """Fetches health reports over a range, paging 30-day windows.

    Returns {start_date, end_date, items} with items merged across windows
    in window order, exact duplicates removed. Each item keeps its own
    `date` and `tz`; `report_data` is passed through in full.
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    items: list = []
    seen: set[str] = set()
    for win_start, win_end in _windows(start, end):  # type: ignore[arg-type]
        response = await governed_get(
            client,
            "/health-reports",
            params={"start_date": win_start, "end_date": win_end},
        )
        data = unwrap(response)
        page_items = data.get("items") if isinstance(data, dict) else None
        for item in page_items or []:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                items.append(item)
    return {"start_date": start_date, "end_date": end_date, "items": items}


def register_health_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_health_reports(start_date: str, end_date: str) -> str:
        """
        Returns Looki daily health reports over a date range. Each item is
        {date, tz, report_data} where report_data carries Looki's own
        observations and estimates (summary, calorie, daily_metrics,
        dietary_review, events, time_range), returned in full — Looki
        content is never truncated in this server. Present these as
        Looki-generated estimates, not medical facts.

        Ranges longer than 30 days are fetched as adjacent non-overlapping
        30-day windows and merged, because the upstream endpoint silently
        truncates wider ranges to their first 30 days.

        Args:
            start_date: Range start, YYYY-MM-DD.
            end_date: Range end, YYYY-MM-DD (inclusive).
        """
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if start is None or end is None:
            return "Error: start_date and end_date must be YYYY-MM-DD dates."
        if start > end:
            return "Error: start_date must be on or before end_date."
        try:
            async with get_client() as client:
                payload = await _fetch_health_reports(client, start_date, end_date)
                return json.dumps(payload, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
