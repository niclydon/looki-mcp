"""Tests for the_unwritten: pure diff + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_the_unwritten.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.tools.insight_memory as mem  # noqa: E402

def _moment(mid, date, *, media=("IMAGE",), start="T10:00:00", end="T10:20:00", loc="Park"):
    return {"id": mid, "date": date, "media_types": list(media),
            "start_time": f"{date}{start}+00:00", "end_time": f"{date}{end}+00:00",
            "cover_file": {"location": loc}, "title": f"m{mid}"}

def test_significance_and_coverage():
    moment_days = [
        {"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]},   # uncovered -> unwritten
        {"date": "2026-06-21", "moments": [_moment("b", "2026-06-21")]},   # covered by single-day journal
        {"date": "2026-06-22", "moments": [_moment("c", "2026-06-22")]},   # covered by multi-day storyboard
    ]
    journal_entries = [
        {"id": "j1", "type": "DIARY", "date": "2026-06-21", "bucket_date": "2026-06-21", "bucket_start_date": None},
        {"id": "j2", "type": "STORYBOARD", "date": "2026-06-23", "bucket_date": "2026-06-23", "bucket_start_date": "2026-06-22"},
    ]
    out = mem._diff_unwritten(moment_days, journal_entries, min_significance=2)
    ids = [m["id"] for m in out["unwritten"]]
    assert ids == ["a"], ids  # only 2026-06-20 uncovered
    assert out["total_moments"] == 3

def test_min_significance_filters():
    # A trivial moment (1 image, short, no location) scores 1; min_significance=2 drops it.
    md = [{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20", media=("IMAGE",), start="T10:00:00", end="T10:01:00", loc=None)]}]
    out = mem._diff_unwritten(md, [], min_significance=2)
    assert out["unwritten"] == [], out

def test_tool_envelope():
    async def fake_gather(days):
        return ([{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]}], [],
                {"calls_used": 2, "days_scanned": days, "capped": None})
    mem._gather_unwritten = fake_gather  # type: ignore
    out = json.loads(asyncio.run(mem._the_unwritten_impl(days=7, min_significance=2)))
    assert [m["id"] for m in out["data"]["unwritten"]] == ["a"]
    assert out["narrative"] is None and out["meta"]["calls_used"] == 2

def main():
    test_significance_and_coverage(); test_min_significance_filters(); test_tool_envelope()
    print("\033[32mPASS\033[0m the_unwritten")

if __name__ == "__main__":
    main()
