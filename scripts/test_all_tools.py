"""Run every registered tool against a running looki-mcp server.

Server must be running on http://localhost:3456/mcp (default) with valid credentials.

For each tool, prints a header, the call result (truncated), and PASS/FAIL.
Tools that need a moment_id / journal_id chain off the result of search_moments,
calendar, or the journals feed.
Covers all 24 tools (dynamic count from server + explicit calls including the
journals family and the MinIO media-capture tools).

Run: .venv/bin/python scripts/test_all_tools.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from fastmcp import Client


SERVER_URL = "http://localhost:3456/mcp"  # default; override in env if testing custom LOOKI_PORT/LOOKI_BIND_HOST
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"


def _truncate(text: str, n: int = 800) -> str:
    if len(text) <= n:
        return text
    return text[:n] + f"\n... [+{len(text) - n} more chars]"


def _is_error(text: str) -> bool:
    return text.startswith("Error:")


def _classify(text: str) -> tuple[str, str]:
    """Return (status, note) — PASS for usable data, SKIP for empty-but-not-error,
    FAIL for actual errors."""
    if _is_error(text):
        return FAIL, text.split("\n", 1)[0]
    try:
        parsed = json.loads(text)
        # Treat empty list/dict as SKIP rather than FAIL — endpoint works, no data
        if isinstance(parsed, list) and len(parsed) == 0:
            return SKIP, "endpoint OK, no data returned"
        if isinstance(parsed, dict) and parsed.get("data") == [] and "moments" not in parsed:
            return SKIP, "endpoint OK, no data returned"
        return PASS, "endpoint returned data"
    except json.JSONDecodeError:
        return FAIL, "non-JSON response"


async def _call(client: Client, name: str, args: dict, label: str | None = None) -> str:
    """Call a tool and return its text content (or stringified error)."""
    label = label or name
    try:
        result = await client.call_tool(name, args)
        return result.content[0].text if result.content else ""
    except Exception as exc:
        return f"Error: {exc}"


def _extract_first_moment_id(text: str) -> str | None:
    """Try to pull a moment id out of a tool response (search/calendar/by_date)."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    # Recursive walk looking for {"id": "..."} that looks like a UUID
    import re
    uuid_pat = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def walk(o):
        if isinstance(o, dict):
            v = o.get("id")
            if isinstance(v, str) and uuid_pat.match(v):
                return v
            for vv in o.values():
                r = walk(vv)
                if r:
                    return r
        elif isinstance(o, list):
            for item in o:
                r = walk(item)
                if r:
                    return r
        return None

    return walk(parsed)


async def main() -> int:
    print(f"Connecting to {SERVER_URL} ...\n")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    results: list[tuple[str, str, str]] = []  # (name, status, note)

    async with Client(SERVER_URL) as client:
        tool_count = len(await client.list_tools())
        print(f"Server reports {tool_count} tools\n")
        print("=" * 80)

        # 1. get_profile
        print("\n[1/24] get_profile()")
        text = await _call(client, "get_profile", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_profile", s, n))

        # 2. get_moments_calendar (30-day window)
        print("\n" + "=" * 80)
        print(f"\n[2/24] get_moments_calendar(start_date={thirty_days_ago}, end_date={today})")
        cal_text = await _call(client, "get_moments_calendar", {
            "start_date": thirty_days_ago, "end_date": today,
        })
        print(_truncate(cal_text, 600))
        s, n = _classify(cal_text)
        print(f"  → {s}: {n}")
        results.append(("get_moments_calendar", s, n))

        # 3. get_recent_activity (default 7 days)
        print("\n" + "=" * 80)
        print("\n[3/24] get_recent_activity()")
        text = await _call(client, "get_recent_activity", {})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_recent_activity", s, n))

        # 4. get_todays_moments
        print("\n" + "=" * 80)
        print("\n[4/24] get_todays_moments()")
        text = await _call(client, "get_todays_moments", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_todays_moments", s, n))

        # 5. get_moments_by_date (today)
        print("\n" + "=" * 80)
        print(f"\n[5/24] get_moments_by_date(date={today})")
        by_date_text = await _call(client, "get_moments_by_date", {"date": today})
        print(_truncate(by_date_text, 600))
        s, n = _classify(by_date_text)
        print(f"  → {s}: {n}")
        results.append(("get_moments_by_date", s, n))

        # 6. search_moments (broad query)
        print("\n" + "=" * 80)
        print("\n[6/24] search_moments(query='morning')")
        search_text = await _call(client, "search_moments", {"query": "morning"})
        print(_truncate(search_text, 800))
        s, n = _classify(search_text)
        print(f"  → {s}: {n}")
        results.append(("search_moments", s, n))

        # Try to find a moment_id from any of the data tools we've called
        moment_id = (
            _extract_first_moment_id(search_text)
            or _extract_first_moment_id(by_date_text)
            or _extract_first_moment_id(cal_text)
        )
        if moment_id:
            print(f"\n  (Using moment_id={moment_id} for detail tools)")
        else:
            print("\n  (No moment_id available — detail tools will be skipped)")

        # 7. get_moment_details
        print("\n" + "=" * 80)
        if moment_id:
            print(f"\n[7/24] get_moment_details(moment_id={moment_id})")
            text = await _call(client, "get_moment_details", {"moment_id": moment_id})
            print(_truncate(text, 600))
            s, n = _classify(text)
        else:
            print("\n[7/24] get_moment_details — skipped (no moment_id)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("get_moment_details", s, n))

        # 8. get_moment_files
        print("\n" + "=" * 80)
        if moment_id:
            print(f"\n[8/24] get_moment_files(moment_id={moment_id}, limit=5)")
            text = await _call(client, "get_moment_files", {"moment_id": moment_id, "limit": 5})
            print(_truncate(text, 600))
            s, n = _classify(text)
        else:
            print("\n[8/24] get_moment_files — skipped (no moment_id)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("get_moment_files", s, n))

        # 9. get_moment_with_media
        print("\n" + "=" * 80)
        if moment_id:
            print(f"\n[9/24] get_moment_with_media(moment_id={moment_id}, media_limit=3)")
            text = await _call(
                client, "get_moment_with_media",
                {"moment_id": moment_id, "media_limit": 3},
            )
            print(_truncate(text, 800))
            s, n = _classify(text)
        else:
            print("\n[9/24] get_moment_with_media — skipped (no moment_id)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("get_moment_with_media", s, n))

        # 10. get_highlights
        print("\n" + "=" * 80)
        print("\n[10/24] get_highlights(limit=5)")
        text = await _call(client, "get_highlights", {"limit": 5})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_highlights", s, n))

        # 11. get_realtime_event
        print("\n" + "=" * 80)
        print("\n[11/24] get_realtime_event()")
        text = await _call(client, "get_realtime_event", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        # Realtime is beta and requires Proactive Mode — error here is expected
        if s == FAIL and "proactive" in text.lower():
            s = SKIP
            n = "expected: requires Proactive Mode"
        print(f"  → {s}: {n}")
        results.append(("get_realtime_event", s, n))

        # 12. describe_realtime_event (extra visual via optional Forge)
        print("\n" + "=" * 80)
        print("\n[12/24] describe_realtime_event()")
        text = await _call(client, "describe_realtime_event", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        if s == FAIL and ("proactive" in text.lower() or "forge" in text.lower() or "image" in text.lower()):
            s = SKIP
            n = "expected: requires Proactive Mode or Forge VLM config"
        print(f"  → {s}: {n}")
        results.append(("describe_realtime_event", s, n))

        # 13. search_moments_with_details
        print("\n" + "=" * 80)
        print("\n[13/24] search_moments_with_details(query='walk', max_results=2)")
        text = await _call(client, "search_moments_with_details", {
            "query": "walk", "max_results": 2,
        })
        print(_truncate(text, 800))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("search_moments_with_details", s, n))

        # 14. extract_video_frames (needs a moment with video; graceful if none)
        print("\n" + "=" * 80)
        if moment_id:
            print(f"\n[14/24] extract_video_frames(moment_id={moment_id}, max_frames=2)")
            text = await _call(client, "extract_video_frames", {"moment_id": moment_id, "max_frames": 2})
            print(_truncate(text, 600))
            s, n = _classify(text)
            # If no video in that moment, the tool returns structured JSON with reason (not Error:)
            if s == PASS and "no_video" in text:
                s = SKIP
                n = "endpoint OK, chosen moment had no video file"
        else:
            print("\n[14/24] extract_video_frames — skipped (no moment_id to test)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("extract_video_frames", s, n))

        # --- journals family (8 tools) ---

        # 15. get_journals_calendar (30-day window)
        print("\n" + "=" * 80)
        print(f"\n[15/24] get_journals_calendar(start_date={thirty_days_ago}, end_date={today})")
        text = await _call(client, "get_journals_calendar", {
            "start_date": thirty_days_ago, "end_date": today,
        })
        print(_truncate(text, 400))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_journals_calendar", s, n))

        # 16. get_journals (summary feed) — also our source for a journal_id
        print("\n" + "=" * 80)
        print("\n[16/24] get_journals(max_days=7, mode='summary')")
        journals_text = await _call(client, "get_journals", {"max_days": 7, "mode": "summary"})
        print(_truncate(journals_text, 800))
        s, n = _classify(journals_text)
        print(f"  → {s}: {n}")
        results.append(("get_journals", s, n))

        journal_id = _extract_first_moment_id(journals_text)
        if journal_id:
            print(f"\n  (Using journal_id={journal_id} for get_journal_entry)")
        else:
            print("\n  (No journal_id available — get_journal_entry will be skipped)")

        # 17. get_journals_by_date (today)
        print("\n" + "=" * 80)
        print(f"\n[17/24] get_journals_by_date(date={today})")
        text = await _call(client, "get_journals_by_date", {"date": today})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_journals_by_date", s, n))

        # 18. get_journal_entry
        print("\n" + "=" * 80)
        if journal_id:
            print(f"\n[18/24] get_journal_entry(journal_id={journal_id})")
            text = await _call(client, "get_journal_entry", {"journal_id": journal_id})
            print(_truncate(text, 600))
            s, n = _classify(text)
        else:
            print("\n[18/24] get_journal_entry — skipped (no journal_id)")
            s, n = SKIP, "no journal_id available"
        print(f"  → {s}: {n}")
        results.append(("get_journal_entry", s, n))

        # 19. get_recent_journals
        print("\n" + "=" * 80)
        print("\n[19/24] get_recent_journals()")
        text = await _call(client, "get_recent_journals", {})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_recent_journals", s, n))

        # 20. get_todays_journal
        print("\n" + "=" * 80)
        print("\n[20/24] get_todays_journal()")
        text = await _call(client, "get_todays_journal", {})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_todays_journal", s, n))

        # 21. backfill_journals (bounded)
        print("\n" + "=" * 80)
        print("\n[21/24] backfill_journals(max_total_days=10, max_pages=2)")
        text = await _call(client, "backfill_journals", {"max_total_days": 10, "max_pages": 2})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("backfill_journals", s, n))

        # 22. search_journals
        print("\n" + "=" * 80)
        print("\n[22/24] search_journals(query='walk')")
        text = await _call(client, "search_journals", {"query": "walk"})
        print(_truncate(text, 800))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("search_journals", s, n))

        # --- media capture (MinIO) ---

        # 23. capture_journal_media (graceful 'disabled' if MinIO unconfigured)
        print("\n" + "=" * 80)
        if journal_id:
            print(f"\n[23/24] capture_journal_media(journal_id={journal_id})")
            text = await _call(client, "capture_journal_media", {"journal_id": journal_id})
            print(_truncate(text, 500))
            s, n = _classify(text)
            if s == PASS and '"status": "disabled"' in text:
                s, n = SKIP, "MinIO not configured"
        else:
            print("\n[23/24] capture_journal_media — skipped (no journal_id)")
            s, n = SKIP, "no journal_id available"
        print(f"  → {s}: {n}")
        results.append(("capture_journal_media", s, n))

        # 24. backfill_journal_media (bounded)
        print("\n" + "=" * 80)
        print("\n[24/24] backfill_journal_media(max_total_days=2, max_pages=1)")
        text = await _call(client, "backfill_journal_media", {"max_total_days": 2, "max_pages": 1})
        print(_truncate(text, 500))
        s, n = _classify(text)
        if s == PASS and '"status": "disabled"' in text:
            s, n = SKIP, "MinIO not configured"
        print(f"  → {s}: {n}")
        results.append(("backfill_journal_media", s, n))

    # Summary
    print("\n" + "=" * 80)
    print("\n=== SUMMARY ===\n")
    width = max(len(r[0]) for r in results)
    for name, status, note in results:
        print(f"  {name:<{width}}  {status}  {note}")
    fails = sum(1 for _, s, _ in results if s == FAIL)
    return 1 if fails > 0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
