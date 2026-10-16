"""Highlights tool: get_highlights.

Highlights are derived client-side from GET /journals. The dedicated
/for_you/items endpoint was retired by Looki in October 2026 (HTTP 400,
envelope code 105, "This endpoint is deprecated. Please use GET /journals
instead"), so the vlog / comic / plog content it used to carry is now
recovered from the journals feed, the same client-side filtering pattern
search_journals uses (upstream silently ignores type=/group= filters on
/journals, so filtering must happen here).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, governed_get, unwrap
from looki_mcp.tools.journals import _flatten_buckets, _shape_media

# Journal types that count as highlights. This type-to-highlights mapping is
# inferred from the observed October 2026 journal vocabulary (a 14-day,
# 119-entry live sample in which DAILY_VLOG / COMIC_PAGE / PLOG were the
# creative, AI-generated formats), NOT from any upstream documentation --
# Looki's published skill doc still describes the retired endpoint. Keep
# this a module-level constant so the mapping is one-line adjustable when
# the upstream vocabulary moves again.
HIGHLIGHT_TYPES = frozenset({"DAILY_VLOG", "COMIC_PAGE", "PLOG"})

# Bounded scan window: the journals feed is paged by a date cursor at up to
# 31 days per request, so a highlights lookup never scans more than
# MAX_SCAN_PAGES pages or MAX_SCAN_DAYS distinct days, whichever comes
# first. Stated in the tool description so callers know the horizon.
MAX_SCAN_PAGES = 6
MAX_SCAN_DAYS = 93
_PAGE_DAYS = 31

_CONTENT_CHAR_CAP = 600


def _date_part(value: Any) -> str | None:
    """Return the YYYY-MM-DD prefix of a timestamp/date string, else None."""
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return None


def _valid_date_arg(value: str | None) -> bool:
    if value is None:
        return True
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    return True


def _in_window(
    entry: dict,
    *,
    recorded_from: str | None = None,
    recorded_to: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> bool:
    """Client-side date-window check against an entry's timestamps."""
    recorded = _date_part(entry.get("recorded_at")) or _date_part(entry.get("date")) or _date_part(entry.get("bucket_date"))
    created = _date_part(entry.get("created_at")) or recorded
    if recorded_from is not None and (recorded is None or recorded < recorded_from):
        return False
    if recorded_to is not None and (recorded is None or recorded > recorded_to):
        return False
    if created_from is not None and (created is None or created < created_from):
        return False
    if created_to is not None and (created is None or created > created_to):
        return False
    return True


def _sort_key(entry: dict) -> str:
    """Newest-first sort key: recorded_at, falling back to created/date."""
    return (
        entry.get("recorded_at")
        or entry.get("created_at")
        or entry.get("date")
        or entry.get("bucket_date")
        or ""
    )


def filter_highlights(
    entries: list[dict],
    limit: int,
    *,
    recorded_from: str | None = None,
    recorded_to: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> list[dict]:
    """Filter journal entries to highlight types, newest first, up to limit.

    Dedupes by entry id (the feed can repeat an entry across buckets) and
    applies the optional recorded/created date windows client-side.
    """
    seen_ids: set[Any] = set()
    picked: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in HIGHLIGHT_TYPES:
            continue
        eid = entry.get("id")
        if eid is not None:
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
        if not _in_window(
            entry,
            recorded_from=recorded_from,
            recorded_to=recorded_to,
            created_from=created_from,
            created_to=created_to,
        ):
            continue
        picked.append(entry)
    picked.sort(key=_sort_key, reverse=True)
    return picked[:limit]


def _shape_highlight(entry: dict) -> dict:
    """Shape one journal entry into the highlights output envelope item.

    Mirrors the retired endpoint's item shape as closely as the journals
    payload allows: id, type, title, description, content (truncated, with
    a flag), timestamps, and media references. Media is URL-free metadata
    (media_type, category, has_thumbnail) reusing the journals shaping, so
    no short-lived temporary_url leaks into a listing; read the entry with
    get_journal_entry for live media URLs.
    """
    media = entry.get("media_items") or []
    content = entry.get("content")
    jid = entry.get("id")
    edate = entry.get("date") or entry.get("bucket_date")
    return {
        "id": jid,
        "type": entry.get("type"),
        "title": entry.get("title"),
        "description": entry.get("description"),
        "content": content[:_CONTENT_CHAR_CAP] if isinstance(content, str) else None,
        "content_truncated": isinstance(content, str) and len(content) > _CONTENT_CHAR_CAP,
        "date": edate,
        "start_date": entry.get("start_date"),
        "recorded_at": entry.get("recorded_at"),
        "created_at": entry.get("created_at"),
        "has_media": len(media) > 0,
        "media_count": len(media),
        "media": [
            _shape_media(m, journal_id=jid, date=edate, idx=i)
            for i, m in enumerate(media)
            if isinstance(m, dict)
        ],
    }


def register_highlights_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_highlights(
        limit: int = 20,
        cursor_id: str | None = None,
        recorded_from: str | None = None,
        recorded_to: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> str:
        """
        Returns AI-generated highlight content created from captured memories —
        vlogs, comics, and photo logs. Use when the user asks to see their
        highlights, creative content, or AI-generated summaries of their memories.

        Highlights are derived from journals since the for_you retirement:
        Looki retired the dedicated highlights endpoint in October 2026, so
        this tool scans the journals feed (GET /journals) and filters
        client-side to the highlight journal types DAILY_VLOG, COMIC_PAGE,
        and PLOG, newest first. The scan is bounded: at most 6 journal pages
        and at most 93 days of journals are scanned per call, so a very old
        highlight may fall outside the window; page deeper with cursor_id.

        Args:
            limit: Number of highlights to return. Between 1 and 100, default 20.
            cursor_id: Pagination cursor from a previous response's
                next_cursor_id (a journal date cursor). Omit for the most
                recent highlights.
            recorded_from: Filter to highlights recorded on or after this date (YYYY-MM-DD).
            recorded_to: Filter to highlights recorded on or before this date (YYYY-MM-DD).
            created_from: Filter to highlights created on or after this date (YYYY-MM-DD).
            created_to: Filter to highlights created on or before this date (YYYY-MM-DD).
        """
        if not (1 <= limit <= 100):
            return "Error: limit must be between 1 and 100."
        for name, value in (
            ("recorded_from", recorded_from),
            ("recorded_to", recorded_to),
            ("created_from", created_from),
            ("created_to", created_to),
        ):
            if not _valid_date_arg(value):
                return f"Error: {name} must be a date in YYYY-MM-DD format."
        try:
            all_entries: list[dict] = []
            seen_dates: set[str] = set()
            cursor = cursor_id
            pages = 0
            upstream_has_more: bool | None = None
            reached_end = False
            async with get_client() as client:
                while pages < MAX_SCAN_PAGES and len(seen_dates) < MAX_SCAN_DAYS:
                    remaining = MAX_SCAN_DAYS - len(seen_dates)
                    params: dict[str, str | int] = {"max_days": min(_PAGE_DAYS, remaining)}
                    if cursor is not None:
                        params["cursor_date"] = cursor
                    # Sequential via governed_get to respect the 60 req/min governor.
                    response = await governed_get(client, "/journals", params=params)
                    data = unwrap(response)
                    pages += 1
                    page_entries = _flatten_buckets(data)
                    for entry in page_entries:
                        day = _date_part(entry.get("date")) or _date_part(entry.get("bucket_date"))
                        if day:
                            seen_dates.add(day)
                    all_entries.extend(page_entries)
                    cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
                    upstream_has_more = data.get("has_more") if isinstance(data, dict) else None
                    if not upstream_has_more or not cursor:
                        reached_end = True
                        break
                    # Enough raw entries to fill the limit: stop early, but
                    # only a tentative count -- the window filters below can
                    # still drop entries, so require a comfortable margin.
                    tentative = filter_highlights(
                        all_entries,
                        limit,
                        recorded_from=recorded_from,
                        recorded_to=recorded_to,
                        created_from=created_from,
                        created_to=created_to,
                    )
                    if len(tentative) >= limit:
                        break
            filtered = filter_highlights(
                all_entries,
                limit + 1,
                recorded_from=recorded_from,
                recorded_to=recorded_to,
                created_from=created_from,
                created_to=created_to,
            )
            has_more = len(filtered) > limit or (not reached_end and cursor is not None)
            items = [_shape_highlight(e) for e in filtered[:limit]]
            out = {
                "source": "journals",
                "item_count": len(items),
                "items": items,
                "next_cursor_id": cursor if has_more else None,
                "has_more": bool(has_more),
                "scanned_entries": len(all_entries),
                "scanned_days": len(seen_dates),
                "pages_fetched": pages,
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
