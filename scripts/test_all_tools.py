"""Run every registered tool against a running looki-mcp server.

Server must be running on http://localhost:3456/mcp with valid credentials.

For each tool, prints a header, the call result (truncated), and PASS/FAIL.
Tools that need a moment_id chain off the result of search_moments / calendar.

Run: .venv/bin/python scripts/test_all_tools.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from fastmcp import Client


SERVER_URL = "http://localhost:3456/mcp"
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
        print("\n[1/12] get_profile()")
        text = await _call(client, "get_profile", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_profile", s, n))

        # 2. get_moments_calendar (30-day window)
        print("\n" + "=" * 80)
        print(f"\n[2/12] get_moments_calendar(start_date={thirty_days_ago}, end_date={today})")
        cal_text = await _call(client, "get_moments_calendar", {
            "start_date": thirty_days_ago, "end_date": today,
        })
        print(_truncate(cal_text, 600))
        s, n = _classify(cal_text)
        print(f"  → {s}: {n}")
        results.append(("get_moments_calendar", s, n))

        # 3. get_recent_activity (default 7 days)
        print("\n" + "=" * 80)
        print("\n[3/12] get_recent_activity()")
        text = await _call(client, "get_recent_activity", {})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_recent_activity", s, n))

        # 4. get_todays_moments
        print("\n" + "=" * 80)
        print("\n[4/12] get_todays_moments()")
        text = await _call(client, "get_todays_moments", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_todays_moments", s, n))

        # 5. get_moments_by_date (today)
        print("\n" + "=" * 80)
        print(f"\n[5/12] get_moments_by_date(date={today})")
        by_date_text = await _call(client, "get_moments_by_date", {"date": today})
        print(_truncate(by_date_text, 600))
        s, n = _classify(by_date_text)
        print(f"  → {s}: {n}")
        results.append(("get_moments_by_date", s, n))

        # 6. search_moments (broad query)
        print("\n" + "=" * 80)
        print("\n[6/12] search_moments(query='morning')")
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
            print(f"\n[7/12] get_moment_details(moment_id={moment_id})")
            text = await _call(client, "get_moment_details", {"moment_id": moment_id})
            print(_truncate(text, 600))
            s, n = _classify(text)
        else:
            print("\n[7/12] get_moment_details — skipped (no moment_id)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("get_moment_details", s, n))

        # 8. get_moment_files
        print("\n" + "=" * 80)
        if moment_id:
            print(f"\n[8/12] get_moment_files(moment_id={moment_id}, limit=5)")
            text = await _call(client, "get_moment_files", {"moment_id": moment_id, "limit": 5})
            print(_truncate(text, 600))
            s, n = _classify(text)
        else:
            print("\n[8/12] get_moment_files — skipped (no moment_id)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("get_moment_files", s, n))

        # 9. get_moment_with_media
        print("\n" + "=" * 80)
        if moment_id:
            print(f"\n[9/12] get_moment_with_media(moment_id={moment_id}, media_limit=3)")
            text = await _call(
                client, "get_moment_with_media",
                {"moment_id": moment_id, "media_limit": 3},
            )
            print(_truncate(text, 800))
            s, n = _classify(text)
        else:
            print("\n[9/12] get_moment_with_media — skipped (no moment_id)")
            s, n = SKIP, "no moment_id available"
        print(f"  → {s}: {n}")
        results.append(("get_moment_with_media", s, n))

        # 10. get_highlights
        print("\n" + "=" * 80)
        print("\n[10/12] get_highlights(limit=5)")
        text = await _call(client, "get_highlights", {"limit": 5})
        print(_truncate(text, 600))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("get_highlights", s, n))

        # 11. get_realtime_event
        print("\n" + "=" * 80)
        print("\n[11/12] get_realtime_event()")
        text = await _call(client, "get_realtime_event", {})
        print(_truncate(text, 400))
        s, n = _classify(text)
        # Realtime is beta and requires Proactive Mode — error here is expected
        if s == FAIL and "proactive" in text.lower():
            s = SKIP
            n = "expected: requires Proactive Mode"
        print(f"  → {s}: {n}")
        results.append(("get_realtime_event", s, n))

        # 12. search_moments_with_details
        print("\n" + "=" * 80)
        print("\n[12/12] search_moments_with_details(query='walk', max_results=2)")
        text = await _call(client, "search_moments_with_details", {
            "query": "walk", "max_results": 2,
        })
        print(_truncate(text, 800))
        s, n = _classify(text)
        print(f"  → {s}: {n}")
        results.append(("search_moments_with_details", s, n))

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
