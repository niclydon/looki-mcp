"""Tests for commitment_harvester: pure transform + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_commitment_harvester.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import looki_mcp.tools.insight_productivity as prod  # noqa: E402

LONG_ITEM = "Follow up with the contractor about " + "the kitchen estimate " * 40

def test_harvest_groups_by_date_and_flags():
    entries = [
        {"id": "e1", "type": "YESTERDAY_RECAP", "date": "2026-06-20",
         "content": "Actionable Suggestions\n- Email Bob\n- Pay rent"},
        {"id": "e2", "type": "DIARY", "date": "2026-06-20", "content": "- not a commitment heading"},
        {"id": "e3", "type": "AUDIO_SUMMARY", "date": "2026-06-19", "title": "Standup",
         "content": "Discussion notes\nTODO: follow up with Sarah"},
        {"id": "e4", "type": "MANUAL_AUDIO_SUMMARY", "date": "2026-06-19",
         "content": "Action Items\n- Book flights"},
        {"id": "e5", "type": "DAILY_VLOG", "date": "2026-06-19"},  # media type: no content key
    ]
    out = prod._harvest_commitments(entries)
    assert out["total"] == 5, out
    assert out["mined_entries"] == 3, out  # DIARY + DAILY_VLOG ignored
    assert [c["text"] for c in out["by_date"]["2026-06-20"]] == ["Email Bob", "Pay rent"]
    assert out["by_date"]["2026-06-20"][0]["parsed_section"] is True
    texts_19 = [c["text"] for c in out["by_date"]["2026-06-19"]]
    assert texts_19 == ["follow up with Sarah", "Book flights"], texts_19
    assert out["by_date"]["2026-06-19"][0]["parsed_section"] is False  # fallback path
    assert out["by_date"]["2026-06-19"][0]["title"] == "Standup"
    assert out["commitment_count"] == 4
    assert out["unparsed_entries"] == 1

def test_duplicate_entry_across_buckets_mined_once():
    e = {"id": "dup", "type": "YESTERDAY_RECAP", "date": "2026-06-20", "content": "TODOs\n- once"}
    out = prod._harvest_commitments([e, dict(e)])
    assert out["mined_entries"] == 1 and out["commitment_count"] == 1, out

def test_item_text_never_truncated():
    out = prod._harvest_commitments([
        {"id": "e1", "type": "AUDIO_SUMMARY", "date": "2026-11-09",
         "content": f"Action Items\n- {LONG_ITEM.strip()}"}])
    assert out["by_date"]["2026-11-09"][0]["text"] == LONG_ITEM.strip()

def test_tool_wraps_in_envelope():
    async def fake_gather(days):
        return ([{"id": "e1", "type": "YESTERDAY_RECAP", "date": "2026-06-20",
                  "content": "TODOs\n- ship it"}],
                {"calls_used": 1, "days_scanned": days, "capped": None})
    saved_gather = prod._gather_journal_entries
    prod._gather_journal_entries = fake_gather  # type: ignore
    saved = prod.llm.llm_configured
    prod.llm.llm_configured = lambda: False
    try:
        out = json.loads(asyncio.run(prod._commitment_harvester_impl(days=7)))
    finally:
        prod.llm.llm_configured = saved
        prod._gather_journal_entries = saved_gather
    assert out["data"]["total"] == 1
    assert out["data"]["by_date"]["2026-06-20"][0]["text"] == "ship it"
    assert out["narrative"] is None              # no LLM configured
    assert out["meta"]["calls_used"] == 1 and out["meta"]["days_scanned"] == 7

def test_gather_uses_journals_feed_not_retired_by_date():
    seen = []
    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        assert not request.url.path.endswith("/journals/by_date")
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {
            "items": [{"date": "2026-11-09", "start_date": None, "journals": [
                {"id": "j1", "type": "AUDIO_SUMMARY", "date": "2026-11-09", "content": "TODO: call Ana"}]}],
            "next_cursor_id": None, "has_more": False}})
    saved = prod.get_client
    prod.get_client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")  # type: ignore
    try:
        entries, meta = asyncio.run(prod._gather_journal_entries(14))
    finally:
        prod.get_client = saved
    assert [p for p, _ in seen] == ["/journals"], seen
    assert seen[0][1]["max_days"] == "14"
    assert entries[0]["id"] == "j1" and entries[0]["bucket_date"] == "2026-11-09"
    assert meta == {"calls_used": 1, "days_scanned": 14, "capped": None}

def test_bad_days_rejected():
    assert asyncio.run(prod._commitment_harvester_impl(days=0)).startswith("Error:")
    assert asyncio.run(prod._commitment_harvester_impl(days=91)).startswith("Error:")

def main():
    test_harvest_groups_by_date_and_flags()
    test_duplicate_entry_across_buckets_mined_once()
    test_item_text_never_truncated()
    test_tool_wraps_in_envelope()
    test_gather_uses_journals_feed_not_retired_by_date()
    test_bad_days_rejected()
    print("\033[32mPASS\033[0m commitment_harvester")

if __name__ == "__main__":
    main()
