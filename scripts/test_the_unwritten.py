"""Tests for the_unwritten: pure diff + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_the_unwritten.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import looki_mcp.tools.insight_memory as mem  # noqa: E402

LONG_AUDIO = "We talked through the renovation plan in detail. " * 40

def _moment(mid, date, *, media=("IMAGE",), start="T10:00:00", end="T10:20:00", loc="Park", **extra):
    return {"id": mid, "date": date, "media_types": list(media),
            "start_time": f"{date}{start}+00:00", "end_time": f"{date}{end}+00:00",
            "cover_file": {"location": loc}, "title": f"m{mid}", **extra}

def test_significance_and_coverage():
    moment_days = [
        {"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]},   # uncovered -> unwritten
        {"date": "2026-06-21", "moments": [_moment("b", "2026-06-21")]},   # covered by single-day DIARY
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

def test_media_only_and_digest_types_do_not_cover():
    moment_days = [{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]}]
    journal_entries = [
        {"id": "v", "type": "DAILY_VLOG", "date": "2026-06-20"},
        {"id": "h", "type": "DAILY_HEALTH_REPORT", "date": "2026-06-20"},
        {"id": "r", "type": "YESTERDAY_RECAP", "date": "2026-06-20"},
    ]
    out = mem._diff_unwritten(moment_days, journal_entries, min_significance=1)
    assert [m["id"] for m in out["unwritten"]] == ["a"], out
    covering = {"id": "s", "type": "AUDIO_SUMMARY", "date": "2026-06-20"}
    out = mem._diff_unwritten(moment_days, journal_entries + [covering], min_significance=1)
    assert out["unwritten"] == [], out

def test_entry_start_date_expands_range():
    moment_days = [{"date": "2026-06-22", "moments": [_moment("c", "2026-06-22")]}]
    entries = [{"id": "s", "type": "STORYBOARD", "date": "2026-06-23", "start_date": "2026-06-21"}]
    assert mem._diff_unwritten(moment_days, entries, min_significance=1)["unwritten"] == []

def test_min_significance_filters():
    # A trivial moment (1 image, short, no location) scores 1; min_significance=2 drops it.
    md = [{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20", media=("IMAGE",), start="T10:00:00", end="T10:01:00", loc=None)]}]
    out = mem._diff_unwritten(md, [], min_significance=2)
    assert out["unwritten"] == [], out

def test_audio_summary_normalized_and_full():
    md = [{"date": "2026-11-09", "moments": [
        _moment("a", "2026-11-09", description="Kitchen walkthrough", audio_summary=LONG_AUDIO),
        _moment("b", "2026-11-09", audio_summary=json.dumps({"text": "Budget call", "topics": ["budget"]})),
        _moment("c", "2026-11-09"),
    ]}]
    out = mem._diff_unwritten(md, [], min_significance=1)
    a, b, c = out["unwritten"]
    assert a["audio_summary"] == {"text": LONG_AUDIO, "topics": [], "truncated": False}
    assert a["description"] == "Kitchen walkthrough"
    assert b["audio_summary"] == {"text": "Budget call", "topics": ["budget"], "truncated": False}
    assert "audio_summary" not in c

def test_tool_envelope():
    async def fake_gather(days):
        return ([{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]}], [],
                {"calls_used": 2, "days_scanned": days, "capped": None})
    saved_gather = mem._gather_unwritten
    mem._gather_unwritten = fake_gather  # type: ignore
    saved = mem.llm.llm_configured
    mem.llm.llm_configured = lambda: False
    try:
        out = json.loads(asyncio.run(mem._the_unwritten_impl(days=7, min_significance=2)))
    finally:
        mem.llm.llm_configured = saved
        mem._gather_unwritten = saved_gather
    assert [m["id"] for m in out["data"]["unwritten"]] == ["a"]
    assert out["narrative"] is None and out["meta"]["calls_used"] == 2

def test_gather_reads_journals_feed_not_retired_by_date():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        assert not request.url.path.endswith("/journals/by_date")
        if request.url.path == "/moments":
            d = request.url.params["on_date"]
            return httpx.Response(200, json={"code": 0, "detail": "ok", "data": [_moment(d, d)]})
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {
            "items": [{"date": "2026-11-10", "start_date": None, "journals": [
                {"id": "j", "type": "DIARY", "date": "2026-11-10"}]}],
            "next_cursor_id": None, "has_more": False}})
    saved = (mem.get_client, mem._days_ago_local, mem._today_local)
    mem.get_client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")  # type: ignore
    mem._days_ago_local = lambda days: "2026-11-09"  # type: ignore
    mem._today_local = lambda: "2026-11-10"  # type: ignore
    try:
        moment_days, entries, meta = asyncio.run(mem._gather_unwritten(1))
    finally:
        mem.get_client, mem._days_ago_local, mem._today_local = saved
    assert paths == ["/moments", "/moments", "/journals"], paths
    assert [d["date"] for d in moment_days] == ["2026-11-09", "2026-11-10"]
    assert meta == {"calls_used": 3, "days_scanned": 2, "capped": None}
    out = mem._diff_unwritten(moment_days, entries, min_significance=1)
    assert [m["id"] for m in out["unwritten"]] == ["2026-11-09"], out

def test_bad_args_rejected():
    assert asyncio.run(mem._the_unwritten_impl(days=32)).startswith("Error:")
    assert asyncio.run(mem._the_unwritten_impl(days=7, min_significance=5)).startswith("Error:")

def main():
    test_significance_and_coverage()
    test_media_only_and_digest_types_do_not_cover()
    test_entry_start_date_expands_range()
    test_min_significance_filters()
    test_audio_summary_normalized_and_full()
    test_tool_envelope()
    test_gather_reads_journals_feed_not_retired_by_date()
    test_bad_args_rejected()
    print("\033[32mPASS\033[0m the_unwritten")

if __name__ == "__main__":
    main()
