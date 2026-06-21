"""Journals tools: the written layer of Looki memory.

The Looki `/journals` family exposes AI-generated long-form text recaps (diary
summaries, dietary/meeting analysis) plus a new class of AI-generated images.
Unlike `/moments` (raw captured media), journal entries are grouped into
per-day *buckets*, and the feed's pagination cursor is a DATE string. See
journals_api_findings.md for the validated mapping.

This module holds the four raw endpoint mirrors AND four timezone-aware /
client-side composites (recent, today, backfill, search). The reshaping helpers
(`_flatten_buckets`, `_shape_entry`, `_by_type_counts`) are module-level so they
can be unit-tested without a server (see scripts/test_journals_helpers.py).

Token discipline: a day holds ~7 entries and the long-form types run ~2–2.5k
chars each, so every listing tool defaults to a truncated `summary` mode. Pass
`mode="full"` for the verbatim payload or `mode="index"` for an id/title spine.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastmcp import FastMCP

from looki_mcp import storage
from looki_mcp.client import format_error, get_client, unwrap
from looki_mcp.config import get_config
from looki_mcp.tools.convenience import _days_ago_local, _today_local, _today_utc

# Valid values for the `mode` knob shared by every listing/composite tool.
_MODES = {"index", "summary", "full"}
# backfill is the highest-volume call, so it forbids 'full' to bound output —
# read individual entries verbatim with get_journal_entry instead.
_BACKFILL_MODES = {"index", "summary"}
_DEFAULT_CHAR_CAP = 600
# Cap the per-object manifest in backfill_journal_media's response so a large
# sweep returns counts + a sample rather than thousands of report dicts.
_BACKFILL_OBJECTS_CAP = 250

# Media temporary_url paths look like /processed/<category>/<file>.jpg — the
# category encodes provenance (dietary_image, user_event_diary_image, etc.).
_PROCESSED_RE = re.compile(r"/processed/([^/]+)/")


def _media_category(url: Any) -> str | None:
    """Extracts the AI-image provenance category from a media temporary_url."""
    if not isinstance(url, str):
        return None
    match = _PROCESSED_RE.search(url)
    return match.group(1) if match else None


def _flatten_buckets(data: Any) -> list[dict]:
    """Flattens the Looki day-bucket structure into a flat list of entries.

    The `/journals` feed wraps entries in per-day buckets
    (`{date, start_date, journals: [...]}`), and a single calendar date can yield
    MULTIPLE buckets (e.g. a multi-day STORYBOARD plus the single-day bucket).
    Each emitted entry is annotated with `bucket_date` / `bucket_start_date` so
    its grouping survives flattening. Tolerates the feed dict shape
    (`{items: [...]}`), the bare `DayBucket[]` shape (from /journals/by_date),
    or junk (returns []).
    """
    if isinstance(data, dict):
        buckets = data.get("items") or []
    elif isinstance(data, list):
        buckets = data
    else:
        return []

    entries: list[dict] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        bucket_date = bucket.get("date")
        bucket_start = bucket.get("start_date")
        for entry in bucket.get("journals") or []:
            if not isinstance(entry, dict):
                continue
            annotated = dict(entry)
            annotated["bucket_date"] = bucket_date
            annotated["bucket_start_date"] = bucket_start
            entries.append(annotated)
    return entries


def _shape_media(item: dict, journal_id: str | None = None, date: str | None = None, idx: int = 0) -> dict:
    """Reshapes one media_item to URL-free metadata.

    Drops BOTH temporary_urls — source and thumbnail alike carry the same
    short-lived (~10 min) JWT, so either would be a dead link by the time an agent
    acts on a listing. Keeps only the media type, provenance category, and a flag
    for whether a thumbnail exists. To get a live image URL, read the entry with
    get_journal_entry (or use mode='full').

    When MinIO is configured, also includes `minio_key` — the deterministic object
    key where the durable copy lives once captured (via capture_journal_media /
    backfill_journal_media / a get_journal_entry read).
    """
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    thumb = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else None
    src_url = source.get("temporary_url")
    shaped = {
        "media_type": source.get("media_type"),
        "category": _media_category(src_url),
        "has_thumbnail": thumb is not None,
    }
    if journal_id and isinstance(src_url, str) and src_url and storage.minio_configured():
        shaped["minio_bucket"] = storage.get_bucket()
        shaped["minio_key"] = storage.media_key(journal_id, date, idx, "source", src_url)
    return shaped


def _shape_entry(entry: dict, mode: str, char_cap: int = _DEFAULT_CHAR_CAP) -> dict:
    """Reshapes a journal entry for a given token budget.

    - `full`    -> the entry unchanged (verbatim content + media).
    - `index`   -> id/type/title/date/has_media spine, NO content or description.
    - `summary` -> the spine plus description, content truncated to `char_cap`
                   (with a `content_truncated` flag), and URL-free media metadata.
    """
    if mode == "full":
        return entry

    media = entry.get("media_items") or []
    shaped = {
        "id": entry.get("id"),
        "type": entry.get("type"),
        "title": entry.get("title"),
        "date": entry.get("date") or entry.get("bucket_date"),
        "start_date": entry.get("start_date"),
        "has_media": len(media) > 0,
        "media_count": len(media),
    }
    if mode == "index":
        return shaped

    content = entry.get("content")
    if isinstance(content, str):
        shaped["content"] = content[:char_cap]
        shaped["content_truncated"] = len(content) > char_cap
    else:
        shaped["content"] = None
        shaped["content_truncated"] = False
    shaped["description"] = entry.get("description")
    shaped["recorded_at"] = entry.get("recorded_at")
    jid = entry.get("id")
    edate = entry.get("date") or entry.get("bucket_date")
    shaped["media"] = [
        _shape_media(m, journal_id=jid, date=edate, idx=i)
        for i, m in enumerate(media)
        if isinstance(m, dict)
    ]
    return shaped


def _by_type_counts(entries: list[dict]) -> dict:
    """Counts entries by `type` — a cheap composition rollup for the agent."""
    counts: dict[str, int] = {}
    for entry in entries:
        etype = entry.get("type")
        if etype:
            counts[etype] = counts.get(etype, 0) + 1
    return counts


def _snippet(text: str, query: str, radius: int = 80) -> str:
    """Returns a ~160-char window of `text` centered on the first `query` hit."""
    low = text.lower()
    idx = low.find(query.lower())
    if idx < 0:
        return text[: radius * 2]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(query) + radius)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _bucket_count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data.get("items") or [])
    return 0


async def _capture_entry_media(entry: dict, *, overwrite: bool = False) -> list[dict]:
    """Downloads every media item (source + thumbnail) of one entry into MinIO.

    Returns a per-object report list. Returns [] when the entry is not a dict or
    has no media; a single [{"status": "skipped", "reason": "minio_not_configured"}]
    when MinIO is unconfigured; otherwise one report per captured/skipped/failed
    object. Never raises — capture failures are reported per object so an
    auto-capture on read can't break the read itself. The temporary_urls must
    still be live (callers pass freshly-fetched entries).
    """
    if not isinstance(entry, dict):
        return []
    media = entry.get("media_items") or []
    if not media:
        return []
    client = storage.get_client()
    if client is None:
        return [{"status": "skipped", "reason": "minio_not_configured"}]
    try:
        await storage.ensure_bucket(client)
    except Exception as exc:
        return [{"status": "failed", "error": f"ensure_bucket: {exc}"[:200]}]

    jid = entry.get("id") or "unknown"
    date = entry.get("date") or entry.get("bucket_date")
    reports: list[dict] = []
    for idx, item in enumerate(media):
        if not isinstance(item, dict):
            continue
        for kind in ("source", "thumbnail"):
            sub = item.get(kind)
            if not isinstance(sub, dict):
                continue
            url = sub.get("temporary_url")
            if not isinstance(url, str) or not url:
                continue
            short_kind = "source" if kind == "source" else "thumb"
            key = storage.media_key(jid, date, idx, short_kind, url)
            report = await storage.capture_url(
                client,
                url,
                key,
                metadata={
                    "journal_id": jid,
                    "type": entry.get("type"),
                    "kind": short_kind,
                    "category": _media_category(url) or "",
                    "recorded_at": entry.get("recorded_at"),
                },
                overwrite=overwrite,
            )
            report["media_index"] = idx
            report["kind"] = short_kind
            reports.append(report)
    return reports


def _capture_summary(reports: list[dict]) -> dict:
    """Roll up a list of capture reports into counts by status."""
    return {
        "captured": sum(1 for r in reports if r.get("status") == "captured"),
        "already_captured": sum(1 for r in reports if r.get("status") == "already_captured"),
        "failed": sum(1 for r in reports if r.get("status") == "failed"),
        "skipped": sum(1 for r in reports if r.get("status") == "skipped"),
    }


def register_journals_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def get_journals(
        cursor_date: str | None = None,
        max_days: int = 7,
        sort_order: str = "DESC",
        mode: str = "summary",
    ) -> str:
        """
        Returns the user's AI-generated journal entries (diary recaps, dietary and
        meeting analysis, storyboards) grouped by day. This is the main journal feed
        and the only tool exposing the date cursor for paging into history. Use for
        "what has my journal said lately?" or to walk backwards through entries.

        Defaults to a token-efficient summary (long entry bodies are truncated). The
        response's `next_cursor_id` is a DATE — pass it back as `cursor_date` to fetch
        the next older page (or use backfill_journals to do that automatically).

        Args:
            cursor_date: Page cursor (YYYY-MM-DD) from a previous response's next_cursor_id. Omit for the most recent entries.
            max_days: Number of distinct days to return. Between 1 and 31, default 7.
            sort_order: Day ordering, 'ASC' or 'DESC'. Default 'DESC' (newest first).
            mode: Detail level — 'index' (id/title spine), 'summary' (truncated content, default), or 'full' (verbatim API payload with raw day-buckets).
        """
        if not (1 <= max_days <= 31):
            return "Error: max_days must be between 1 and 31."
        if sort_order not in {"ASC", "DESC"}:
            return "Error: sort_order must be 'ASC' or 'DESC'."
        if mode not in _MODES:
            return f"Error: mode must be one of {sorted(_MODES)}."
        try:
            params: dict[str, str | int] = {"max_days": max_days}
            if cursor_date is not None:
                params["cursor_date"] = cursor_date
            # Only send sort_order when overriding the default — passing it
            # explicitly alters ordering subtly (see journals_api_findings.md).
            if sort_order != "DESC":
                params["sort_order"] = sort_order
            async with get_client() as client:
                response = await client.get("/journals", params=params)
                data = unwrap(response)
            if mode == "full":
                return json.dumps(data, indent=2)
            entries = _flatten_buckets(data)
            out = {
                "max_days": max_days,
                "entry_count": len(entries),
                "by_type": _by_type_counts(entries),
                "next_cursor_id": data.get("next_cursor_id") if isinstance(data, dict) else None,
                "has_more": data.get("has_more") if isinstance(data, dict) else None,
                "entries": [_shape_entry(e, mode) for e in entries],
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_journals_calendar(start_date: str, end_date: str) -> str:
        """
        Returns which days within a date range have journal entries. The cheapest
        journal call (one date string per active day, no content) — use it to scope a
        window before pulling entries, or to answer "which days did I journal?".

        Args:
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
        """
        try:
            async with get_client() as client:
                response = await client.get(
                    "/journals/calendar",
                    params={"start_date": start_date, "end_date": end_date},
                )
                return json.dumps(unwrap(response), indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_journals_by_date(date: str, mode: str = "summary") -> str:
        """
        Returns all journal entries for one specific date. This is the correct way to
        read a single day (the feed's day cursor cannot target an arbitrary date). A
        date may carry several entries (diary vignettes, a dietary log, the daily
        recap) and occasionally multiple buckets (e.g. a multi-day storyboard).

        Args:
            date: The date to retrieve, in YYYY-MM-DD format.
            mode: Detail level — 'index', 'summary' (default), or 'full' (verbatim payload).
        """
        if mode not in _MODES:
            return f"Error: mode must be one of {sorted(_MODES)}."
        try:
            async with get_client() as client:
                response = await client.get("/journals/by_date", params={"on_date": date})
                data = unwrap(response)
            if mode == "full":
                return json.dumps(data, indent=2)
            entries = _flatten_buckets(data)
            out = {
                "date": date,
                "bucket_count": _bucket_count(data),
                "entry_count": len(entries),
                "by_type": _by_type_counts(entries),
                "entries": [_shape_entry(e, mode) for e in entries],
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_journal_entry(journal_id: str) -> str:
        """
        Returns the full, untruncated details of a single journal entry by its UUID,
        including the complete content body and all media items with live (short-lived,
        ~10 min) image URLs. Use after a listing/search tool hands back an entry id to
        read the entire entry. Re-fetch this entry if a media URL has expired.

        Side effect: when MinIO is configured, this also captures the entry's media to
        durable object storage on read (idempotent — already-stored media is skipped).
        On success the response is {entry, media_capture}, where media_capture reports
        what was stored; on failure it returns an `Error: ...` string instead.

        Args:
            journal_id: UUID of the journal entry to retrieve.
        """
        try:
            async with get_client() as client:
                response = await client.get(f"/journals/{journal_id}")
                entry = unwrap(response)
            # Auto-capture media while its temporary_urls are still fresh. Failures
            # are reported, never raised, so the read always succeeds.
            capture = await _capture_entry_media(entry) if isinstance(entry, dict) else []
            return json.dumps(
                {"entry": entry, "media_capture": {**_capture_summary(capture), "objects": capture}},
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_recent_journals(days: int = 7, mode: str = "summary") -> str:
        """
        Returns journal entries from the last N days ending today — the journal twin of
        get_recent_activity. Timezone-aware ("today" uses LOOKI_USER_TIMEZONE, else
        UTC) and needs no cursor. Use for "recap my week" or "what have my journals said
        lately?". The `by_type` rollup shows the day mix so you can expand selectively.

        Args:
            days: Number of days to look back. Between 1 and 31, default 7.
            mode: Detail level — 'index', 'summary' (default), or 'full'.
        """
        if not (1 <= days <= 31):
            return "Error: days must be between 1 and 31."
        if mode not in _MODES:
            return f"Error: mode must be one of {sorted(_MODES)}."
        tz = get_config().user_timezone or "UTC"
        end_local = _today_local()
        start_local = _days_ago_local(days)
        end_utc = _today_utc()
        start_utc = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            async with get_client() as client:
                response = await client.get("/journals", params={"max_days": days})
                data = unwrap(response)
            entries = _flatten_buckets(data)
            out = {
                "period": {
                    "days": days,
                    "timezone": tz,
                    "start_date_local": start_local,
                    "end_date_local": end_local,
                    "start_date_utc": start_utc,
                    "end_date_utc": end_utc,
                },
                "entry_count": len(entries),
                "by_type": _by_type_counts(entries),
                "next_cursor_id": data.get("next_cursor_id") if isinstance(data, dict) else None,
                "has_more": data.get("has_more") if isinstance(data, dict) else None,
                "entries": [_shape_entry(e, mode) for e in entries],
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def get_todays_journal(mode: str = "summary") -> str:
        """
        Returns today's journal entries, with the daily recap (YESTERDAY_RECAP) surfaced
        first when present. "Today" is computed in the configured timezone
        (LOOKI_USER_TIMEZONE), or UTC if unset. Use for "what does my journal say about
        today?" or "give me today's recap".

        Args:
            mode: Detail level — 'index', 'summary' (default), or 'full'.
        """
        if mode not in _MODES:
            return f"Error: mode must be one of {sorted(_MODES)}."
        tz = get_config().user_timezone or "UTC"
        date_local = _today_local()
        date_utc = _today_utc()
        try:
            async with get_client() as client:
                response = await client.get("/journals/by_date", params={"on_date": date_local})
                data = unwrap(response)
            entries = _flatten_buckets(data)
            # Lead with the flagship daily narrative; stable sort keeps the rest in order.
            entries.sort(key=lambda e: 0 if e.get("type") == "YESTERDAY_RECAP" else 1)
            out = {
                "date_local": date_local,
                "date_utc": date_utc,
                "timezone": tz,
                "entry_count": len(entries),
                "by_type": _by_type_counts(entries),
                "entries": [_shape_entry(e, mode) for e in entries],
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def backfill_journals(
        cursor_date: str | None = None,
        max_total_days: int = 31,
        mode: str = "index",
        max_pages: int = 6,
    ) -> str:
        """
        Walks the journal feed backwards through history in one call, following the date
        cursor across pages until it runs out or hits a cap. Use to load deep history
        ("everything from the last two months"). Defaults to 'index' mode (id/title spine,
        no content) because this is the highest-volume call. To bound output, 'full' is
        not offered here — read individual entries in full with get_journal_entry. Returns
        `next_cursor_date` so you can resume deeper.

        Args:
            cursor_date: Start paging strictly before this date (YYYY-MM-DD). Omit to start at the most recent entries.
            max_total_days: Hard cap on distinct days to fetch. Between 1 and 93, default 31.
            mode: Detail level — 'index' (default) or 'summary' (truncated content). 'full' is intentionally disallowed for this high-volume tool.
            max_pages: Hard cap on API requests (each up to 31 days). Between 1 and 12, default 6.
        """
        if not (1 <= max_total_days <= 93):
            return "Error: max_total_days must be between 1 and 93."
        if not (1 <= max_pages <= 12):
            return "Error: max_pages must be between 1 and 12."
        if mode not in _BACKFILL_MODES:
            return f"Error: mode must be one of {sorted(_BACKFILL_MODES)} (use get_journal_entry for full content)."
        try:
            all_entries: list[dict] = []
            seen_ids: set[str] = set()
            seen_dates: set[str] = set()
            cursor = cursor_date
            pages = 0
            reached_end = False
            async with get_client() as client:
                while pages < max_pages and len(seen_dates) < max_total_days:
                    remaining = max_total_days - len(seen_dates)
                    params: dict[str, str | int] = {"max_days": min(31, remaining)}
                    if cursor is not None:
                        params["cursor_date"] = cursor
                    # Sequential (not gathered) to respect the 60 req/min limit.
                    response = await client.get("/journals", params=params)
                    data = unwrap(response)
                    pages += 1
                    for entry in _flatten_buckets(data):
                        eid = entry.get("id")
                        if eid in seen_ids:
                            continue
                        seen_ids.add(eid)
                        if entry.get("date"):
                            seen_dates.add(entry["date"])
                        all_entries.append(entry)
                    cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
                    has_more = data.get("has_more") if isinstance(data, dict) else False
                    if not has_more or not cursor:
                        reached_end = True
                        break
            dates = sorted(seen_dates)
            out = {
                "entry_count": len(all_entries),
                "days_covered": len(seen_dates),
                "oldest_date": dates[0] if dates else None,
                "newest_date": dates[-1] if dates else None,
                "pages_fetched": pages,
                "reached_end": reached_end,
                "next_cursor_date": None if reached_end else cursor,
                "by_type": _by_type_counts(all_entries),
                "entries": [_shape_entry(e, mode) for e in all_entries],
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def search_journals(query: str, days: int = 31, max_results: int = 10) -> str:
        """
        Finds journal entries whose title, description, or content contain the query
        (case-insensitive substring match) within the recent `days` window. Looki has no
        server-side journal search, so this is a local locator: it returns matched entries
        with a snippet and id — use get_journal_entry to read a full match. Only searches
        the recent window; widen `days` (max 31) or use backfill_journals for deep history.

        Args:
            query: Text to find. Between 1 and 100 characters.
            days: How many recent days to search. Between 1 and 31, default 31.
            max_results: Maximum matches to return. Between 1 and 25, default 10.
        """
        if not query or len(query) > 100:
            return "Error: query must be between 1 and 100 characters."
        if not (1 <= days <= 31):
            return "Error: days must be between 1 and 31."
        if not (1 <= max_results <= 25):
            return "Error: max_results must be between 1 and 25."
        needle = query.lower()
        try:
            async with get_client() as client:
                response = await client.get("/journals", params={"max_days": days})
                data = unwrap(response)
            entries = _flatten_buckets(data)
            matches: list[dict] = []
            for entry in entries:
                for field in ("title", "description", "content"):
                    value = entry.get(field)
                    if isinstance(value, str) and needle in value.lower():
                        shaped = _shape_entry(entry, "summary")
                        shaped["matched_field"] = field
                        shaped["snippet"] = _snippet(value, query)
                        matches.append(shaped)
                        break
            out = {
                "query": query,
                "window_days": days,
                "scanned_entries": len(entries),
                "match_count": len(matches),
                "returned": min(len(matches), max_results),
                "matches": matches[:max_results],
            }
            return json.dumps(out, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def capture_journal_media(journal_id: str, overwrite: bool = False) -> str:
        """
        Downloads one journal entry's AI-generated media (images) into durable MinIO
        object storage. Journal media URLs are short-lived (~10 min) JWTs, so this makes
        a permanent copy. Idempotent: media already stored is reported as
        already_captured and not re-downloaded unless overwrite=True. Use this to
        deliberately preserve a specific entry's images.

        Returns the object keys and a per-status rollup. Requires MinIO to be configured
        (MINIO_* env vars); otherwise returns a disabled status.

        Args:
            journal_id: UUID of the journal entry whose media to capture.
            overwrite: Re-download and overwrite even if the object already exists. Default False.
        """
        if not storage.minio_configured():
            return json.dumps(
                {"status": "disabled", "reason": "MINIO_* env vars not configured", "journal_id": journal_id},
                indent=2,
            )
        try:
            async with get_client() as client:
                response = await client.get(f"/journals/{journal_id}")
                entry = unwrap(response)
            reports = await _capture_entry_media(entry, overwrite=overwrite)
            media_total = (
                len([m for m in (entry.get("media_items") or []) if isinstance(m, dict)])
                if isinstance(entry, dict)
                else 0
            )
            return json.dumps(
                {
                    "journal_id": journal_id,
                    "bucket": storage.get_bucket(),
                    "media_items": media_total,
                    **_capture_summary(reports),
                    "objects": reports,
                },
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"

    @mcp.tool
    async def backfill_journal_media(
        cursor_date: str | None = None,
        max_total_days: int = 31,
        max_pages: int = 6,
        overwrite: bool = False,
    ) -> str:
        """
        Sweeps journal history and captures ALL media into durable MinIO storage before
        the short-lived (~10 min) URLs expire. Walks the feed backwards by date cursor
        (bounded by the same caps as backfill_journals) and stores every image it finds.
        Idempotent: already-stored media is skipped, so re-running is cheap. This is the
        tool to run to guarantee durable copies of historical journal media.

        Requires MinIO to be configured (MINIO_* env vars); otherwise returns disabled.

        Args:
            cursor_date: Start paging strictly before this date (YYYY-MM-DD). Omit to start at the most recent entries.
            max_total_days: Hard cap on distinct days to sweep. Between 1 and 93, default 31.
            max_pages: Hard cap on API requests (each up to 31 days). Between 1 and 12, default 6.
            overwrite: Re-download and overwrite existing objects. Default False.
        """
        if not storage.minio_configured():
            return json.dumps(
                {"status": "disabled", "reason": "MINIO_* env vars not configured"}, indent=2
            )
        if not (1 <= max_total_days <= 93):
            return "Error: max_total_days must be between 1 and 93."
        if not (1 <= max_pages <= 12):
            return "Error: max_pages must be between 1 and 12."
        try:
            seen_dates: set[str] = set()
            cursor = cursor_date
            pages = 0
            reached_end = False
            entries_with_media = 0
            all_reports: list[dict] = []
            async with get_client() as client:
                while pages < max_pages and len(seen_dates) < max_total_days:
                    remaining = max_total_days - len(seen_dates)
                    params: dict[str, str | int] = {"max_days": min(31, remaining)}
                    if cursor is not None:
                        params["cursor_date"] = cursor
                    response = await client.get("/journals", params=params)
                    data = unwrap(response)
                    pages += 1
                    for entry in _flatten_buckets(data):
                        if entry.get("date"):
                            seen_dates.add(entry["date"])
                        if entry.get("media_items"):
                            entries_with_media += 1
                            all_reports.extend(await _capture_entry_media(entry, overwrite=overwrite))
                    cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
                    has_more = data.get("has_more") if isinstance(data, dict) else False
                    if not has_more or not cursor:
                        reached_end = True
                        break
            return json.dumps(
                {
                    "bucket": storage.get_bucket(),
                    "days_covered": len(seen_dates),
                    "pages_fetched": pages,
                    "reached_end": reached_end,
                    "next_cursor_date": None if reached_end else cursor,
                    "entries_with_media": entries_with_media,
                    **_capture_summary(all_reports),
                    "objects_total": len(all_reports),
                    "objects_truncated": len(all_reports) > _BACKFILL_OBJECTS_CAP,
                    "objects": all_reports[:_BACKFILL_OBJECTS_CAP],
                },
                indent=2,
            )
        except Exception as exc:
            return f"Error: {format_error(exc)}"
