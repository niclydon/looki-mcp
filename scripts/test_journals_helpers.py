"""Unit tests for the pure journals reshaping helpers (no server, no .env).

Covers the day-bucket -> entry flattening and the index/summary/full shaping that
the journals tools depend on. These are the highest-risk pieces (the Looki
/journals feed groups entries into day-buckets, and a single date can yield
multiple buckets), so they're tested in isolation.

Run: .venv/bin/python scripts/test_journals_helpers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools.journals import (  # noqa: E402
    _by_type_counts,
    _flatten_buckets,
    _media_category,
    _shape_entry,
)


# --- fixtures ---------------------------------------------------------------

def _entry(eid, etype, *, title=None, description="d", content=None, media=0, date="2026-06-18", start_date=None):
    items = []
    for i in range(media):
        # BOTH source and thumbnail carry a short-lived JWT — neither may leak in
        # summary mode (regression guard for the thumbnail-url leak).
        items.append({
            "source": {
                "temporary_url": f"https://user.file.devo.looki.ai/u/processed/user_event_diary_image/{eid}-{i}.jpg?x-looki-token=SRC_SECRET",
                "media_type": "IMAGE",
            },
            "thumbnail": {
                "temporary_url": f"https://user.file.devo.looki.ai/u/processed/user_event_diary_image/{eid}-{i}_thumb.jpg?x-looki-token=THUMB_SECRET",
                "media_type": "IMAGE",
            },
        })
    return {
        "id": eid,
        "type": etype,
        "title": title,
        "description": description,
        "content": content,
        "media_items": items,
        "date": date,
        "start_date": start_date,
        "tz": "-04:00",
        "recorded_at": f"{date}T12:00:00-04:00",
        "created_at": f"{date}T12:05:00-04:00",
    }


# A multi-day STORYBOARD bucket + a regular single-day bucket (5 DIARY + 1 DIETARY + 1 YESTERDAY_RECAP)
LONG = "x" * 2000
FEED = {
    "items": [
        {
            "date": "2026-06-18",
            "start_date": "2026-06-17",
            "journals": [_entry("sb1", "STORYBOARD", title="Big Day", content=None, media=1, date="2026-06-18", start_date="2026-06-17")],
        },
        {
            "date": "2026-06-18",
            "start_date": None,
            "journals": [
                _entry("di1", "DIARY", description="store run", content="store run", media=1),
                _entry("di2", "DIARY", media=0),
                _entry("di3", "DIARY", media=1),
                _entry("di4", "DIARY", media=0),
                _entry("di5", "DIARY", media=1),
                _entry("dt1", "DIETARY", title="Lunch", content=LONG, media=1),
                _entry("yr1", "YESTERDAY_RECAP", content=LONG, media=0),
            ],
        },
    ],
    "next_cursor_id": "2026-06-17",
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
    print("test _flatten_buckets")
    flat = _flatten_buckets(FEED)
    check(len(flat) == 8, f"flattens 1 storyboard + 7 day entries -> 8 (got {len(flat)})")
    check(all("bucket_date" in e for e in flat), "every flattened entry is annotated with bucket_date")
    sb = next(e for e in flat if e["id"] == "sb1")
    check(sb["bucket_date"] == "2026-06-18" and sb["bucket_start_date"] == "2026-06-17",
          "multi-day storyboard keeps bucket date + start_date")

    # tolerate the bare-list shape returned by /journals/by_date
    bare = FEED["items"]
    check(len(_flatten_buckets(bare)) == 8, "tolerates a bare DayBucket[] (by_date shape)")
    # tolerate junk
    check(_flatten_buckets(None) == [] and _flatten_buckets("nope") == [], "non-dict/list input -> []")
    check(_flatten_buckets({"items": []}) == [], "empty items -> []")

    print("test _by_type_counts")
    counts = _by_type_counts(flat)
    check(counts.get("DIARY") == 5 and counts.get("DIETARY") == 1
          and counts.get("YESTERDAY_RECAP") == 1 and counts.get("STORYBOARD") == 1,
          f"counts entries by type (got {counts})")

    print("test _shape_entry index")
    idx = _shape_entry(flat[0], "index")
    check(set(idx.keys()) >= {"id", "type", "title", "date", "has_media"}, "index has the spine keys")
    check("content" not in idx and "description" not in idx, "index drops content AND description")
    check(idx["has_media"] is True and idx["media_count"] == 1, "index reports media presence/count without URLs")

    print("test _shape_entry summary")
    dietary = next(e for e in flat if e["id"] == "dt1")
    summ = _shape_entry(dietary, "summary", char_cap=600)
    check(summ.get("description") == "d", "summary includes description")
    check(len(summ.get("content", "")) == 600 and summ.get("content_truncated") is True,
          "summary truncates long content at char_cap and flags it")
    blob = repr(summ)
    check("SRC_SECRET" not in blob and "THUMB_SECRET" not in blob and "x-looki-token" not in blob,
          "summary never leaks a short-lived JWT (source OR thumbnail temporary_url)")
    check("thumbnail_url" not in blob, "summary drops the thumbnail_url key entirely")
    check(summ["media"][0].get("has_thumbnail") is True, "summary flags has_thumbnail without exposing the URL")
    check("user_event_diary_image" in blob, "summary surfaces the media category (cheap, URL-free)")

    print("test _shape_entry summary on null-content type")
    sb_summ = _shape_entry(sb, "summary")
    check(sb_summ.get("content") is None and sb_summ.get("content_truncated") is False,
          "STORYBOARD (content=null) -> content None, not truncated")

    print("test _shape_entry full = raw passthrough")
    full = _shape_entry(dietary, "full")
    check(full.get("content") == LONG, "full keeps verbatim untruncated content")

    print("test _media_category")
    check(_media_category("https://h/u/processed/dietary_image/123.jpg?x=y") == "dietary_image",
          "extracts /processed/<category>/ from a media URL")
    check(_media_category(None) is None and _media_category("nope") is None, "bad URL -> None")

    print()
    if failures:
        print(f"FAILED ({len(failures)})")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
