"""Summaries tool: get_summaries.

Life summaries are a distinct Looki record type from journals: daily and
weekly life summaries, chat summaries, and moment summaries, each a prose
record keyed by `on_date`. Journals are creative artifacts (diary recaps,
comics, vlogs); summaries are the life-summary records. Do not substitute
one for the other.

Upstream range contract (verified live 2026-11-09): the endpoint rejects
spans longer than 7 days for the daily-type records (HTTP 400, envelope
code 100), so this tool pages longer ranges as adjacent non-overlapping
7-day windows and merges the items, per the official skill's guidance.
The required query params are exactly `start_date` / `end_date` — passing
`date=` or `from_date`/`to_date` returns a misleading 400 code 100
"Date parameter is required".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, governed_get, unwrap

SUMMARY_TYPES = ("daily", "weekly", "chat", "moment")

# Longest span the upstream endpoint accepts for every summary type
# (daily verified live 2026-11-09: 7 days OK, 8 days -> 400 code 100).
_RANGE_WINDOW_DAYS = 7


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    """Splits [start, end] into adjacent non-overlapping <=7-day windows."""
    out: list[tuple[str, str]] = []
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=_RANGE_WINDOW_DAYS - 1), end)
        out.append((cur.strftime("%Y-%m-%d"), win_end.strftime("%Y-%m-%d")))
        cur = win_end + timedelta(days=1)
    return out


async def _fetch_summaries(client, start_date: str, end_date: str, summary_type: str) -> dict:
    """Fetches one summary type over a range, paging 7-day windows.

    Returns {type, start_date, end_date, items} with items merged across
    windows in window order, exact duplicates removed. Raises on upstream
    errors (callers surface them via format_error).
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    items: list = []
    seen: set[str] = set()
    for win_start, win_end in _windows(start, end):  # type: ignore[arg-type]
        response = await governed_get(
            client,
            "/summaries",
            params={"start_date": win_start, "end_date": win_end, "type": summary_type},
        )
        data = unwrap(response)
        page_items = data.get("items") if isinstance(data, dict) else None
        for item in page_items or []:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                items.append(item)
    return {
        "type": summary_type,
        "start_date": start_date,
        "end_date": end_date,
        "items": items,
    }


def register_summaries_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_summaries(start_date: str, end_date: str, type: str) -> str:
        """
        Returns Looki life summaries of one type over a date range. Each item
        is {on_date, summary} with the summary text in full — Looki content is
        never truncated in this server.

        Summaries are life-summary records, distinct from journals (creative
        artifacts like diary recaps and comics): use this tool for daily or
        weekly life summaries and for summaries of the user's chats with the
        Looki assistant.

        Ranges longer than 7 days are fetched as adjacent non-overlapping
        7-day windows and merged, because the upstream endpoint rejects
        longer spans for the daily-type records.

        Args:
            start_date: Range start, YYYY-MM-DD.
            end_date: Range end, YYYY-MM-DD (inclusive).
            type: One of daily | weekly | chat | moment (lowercase only).
        """
        if type not in SUMMARY_TYPES:
            return (
                "Error: type must be one of daily, weekly, chat, moment "
                f"(lowercase); got {type!r}."
            )
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if start is None or end is None:
            return "Error: start_date and end_date must be YYYY-MM-DD dates."
        if start > end:
            return "Error: start_date must be on or before end_date."
        try:
            async with get_client() as client:
                payload = await _fetch_summaries(client, start_date, end_date, type)
                return json.dumps(payload, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
