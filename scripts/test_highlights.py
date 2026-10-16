"""Unit tests for get_highlights journals-composite helpers (no server, no .env).

Replaces scripts/test_highlights_group.py: the group/order validators it
covered belonged to the retired highlights endpoint (Looki retired it in
October 2026) and were deleted with that call path. Highlights are now
derived client-side from GET /journals, so coverage targets the type
filter, the limit, newest-first ordering, the date windows, dedupe, and
the shaped output envelope, using recorded-shape journal fixtures.

Run: .venv/bin/python scripts/test_highlights.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools.highlights import (  # noqa: E402
    HIGHLIGHT_TYPES,
    MAX_SCAN_DAYS,
    MAX_SCAN_PAGES,
    _shape_highlight,
    filter_highlights,
)
from looki_mcp.tools.journals import _flatten_buckets  # noqa: E402


def _entry(eid, etype, *, date="2026-10-10", recorded=None, created=None, title=None, content="body", media=0):
    items = []
    for i in range(media):
        items.append({
            "source": {
                "temporary_url": f"https://user.file.devo.looki.ai/u/processed/comic_image/{eid}-{i}.jpg?x-looki-token=SRC_SECRET",
                "media_type": "IMAGE",
            },
            "thumbnail": {
                "temporary_url": f"https://user.file.devo.looki.ai/u/processed/comic_image/{eid}-{i}_thumb.jpg?x-looki-token=THUMB_SECRET",
                "media_type": "IMAGE",
            },
        })
    return {
        "id": eid,
        "type": etype,
        "title": title or f"title-{eid}",
        "description": f"desc-{eid}",
        "content": content,
        "media_items": items,
        "date": date,
        "start_date": None,
        "recorded_at": recorded or f"{date}T12:00:00-04:00",
        "created_at": created or f"{date}T12:05:00-04:00",
    }


# Recorded-shape feed: day buckets wrapping a mixed-type journal set.
FEED = {
    "items": [
        {
            "date": "2026-10-12",
            "start_date": None,
            "journals": [
                _entry("vlog1", "DAILY_VLOG", date="2026-10-12", recorded="2026-10-12T09:00:00-04:00", media=1),
                _entry("diary1", "DIARY", date="2026-10-12"),
                _entry("comic1", "COMIC_PAGE", date="2026-10-12", recorded="2026-10-12T18:00:00-04:00", media=1),
            ],
        },
        {
            "date": "2026-10-11",
            "start_date": None,
            "journals": [
                _entry("plog1", "PLOG", date="2026-10-11", recorded="2026-10-11T10:00:00-04:00", media=2),
                _entry("diet1", "DIETARY", date="2026-10-11"),
                _entry("recap1", "YESTERDAY_RECAP", date="2026-10-11"),
                _entry("story1", "STORYBOARD", date="2026-10-11"),
                _entry("vlog2", "DAILY_VLOG", date="2026-10-11", recorded="2026-10-11T08:00:00-04:00"),
            ],
        },
        {
            "date": "2026-10-10",
            "start_date": None,
            "journals": [
                _entry("comic2", "COMIC_PAGE", date="2026-10-10", recorded="2026-10-10T20:00:00-04:00"),
            ],
        },
    ],
    "next_cursor_id": "2026-10-09",
    "has_more": True,
}

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok: {msg}")


def main() -> int:
    print("test HIGHLIGHT_TYPES + scan caps")
    check(HIGHLIGHT_TYPES == frozenset({"DAILY_VLOG", "COMIC_PAGE", "PLOG"}),
          f"highlight type set is the inferred Oct 2026 set (got {sorted(HIGHLIGHT_TYPES)})")
    check(MAX_SCAN_PAGES >= 1 and MAX_SCAN_DAYS >= 1, "scan window caps are positive/bounded")

    entries = _flatten_buckets(FEED)
    check(len(entries) == 9, f"fixture flattens to 9 entries (got {len(entries)})")

    print("test type filter")
    picked = filter_highlights(entries, 20)
    types = [e["type"] for e in picked]
    check(all(t in HIGHLIGHT_TYPES for t in types), f"only highlight types survive (got {types})")
    check(len(picked) == 5, f"5 of 9 fixture entries are highlights (got {len(picked)})")
    check(not any(e["type"] in {"DIARY", "DIETARY", "YESTERDAY_RECAP", "STORYBOARD"} for e in picked),
          "DIARY/DIETARY/YESTERDAY_RECAP/STORYBOARD are excluded")

    print("test newest-first ordering")
    ids = [e["id"] for e in picked]
    check(ids == ["comic1", "vlog1", "plog1", "vlog2", "comic2"],
          f"newest first by recorded_at (got {ids})")
    shuffled = list(reversed(entries))
    check([e["id"] for e in filter_highlights(shuffled, 20)] == ids,
          "ordering holds even when the feed order is shuffled")

    print("test limit")
    check([e["id"] for e in filter_highlights(entries, 2)] == ["comic1", "vlog1"],
          "limit=2 returns the two newest highlights")
    check(filter_highlights(entries, 0) == [], "limit=0 returns nothing")
    check(len(filter_highlights(entries, 100)) == 5, "limit above match count returns all matches")

    print("test dedupe")
    dup = entries + [dict(entries[2])]  # comic1 repeated across buckets
    check(len(filter_highlights(dup, 20)) == 5, "duplicate entry ids are returned once")

    print("test date windows")
    win = filter_highlights(entries, 20, recorded_from="2026-10-11", recorded_to="2026-10-11")
    check([e["id"] for e in win] == ["plog1", "vlog2"],
          f"recorded window keeps only 2026-10-11 highlights (got {[e['id'] for e in win]})")
    win2 = filter_highlights(entries, 20, created_from="2026-10-12")
    check([e["id"] for e in win2] == ["comic1", "vlog1"],
          "created_from window filters on created_at")

    print("test _shape_highlight envelope")
    shaped = _shape_highlight(next(e for e in entries if e["id"] == "plog1"))
    for key in ("id", "type", "title", "description", "content", "date",
                "recorded_at", "created_at", "has_media", "media_count", "media"):
        check(key in shaped, f"shaped item carries {key}")
    check(shaped["has_media"] is True and shaped["media_count"] == 2, "media presence/count preserved")
    check(shaped["media"][0].get("has_thumbnail") is True, "thumbnail presence is flagged when present")
    blob = repr(shaped)
    check("SRC_SECRET" not in blob and "THUMB_SECRET" not in blob and "x-looki-token" not in blob,
          "shaped item never leaks a short-lived media temporary_url")
    long_entry = _entry("long1", "PLOG", content="x" * 2000)
    long_shaped = _shape_highlight(long_entry)
    check(len(long_shaped["content"]) == 600 and long_shaped["content_truncated"] is True,
          "long content is truncated at the cap and flagged")

    print()
    if failures:
        print(f"FAILED ({len(failures)})")
        return 1
    print("PASS highlights")
    return 0


if __name__ == "__main__":
    sys.exit(main())
