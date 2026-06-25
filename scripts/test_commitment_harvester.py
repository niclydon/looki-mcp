"""Tests for commitment_harvester: pure transform + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_commitment_harvester.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.tools.insight_productivity as prod  # noqa: E402

def test_harvest_groups_by_date_and_flags():
    entries = [
        {"id": "e1", "type": "YESTERDAY_RECAP", "date": "2026-06-20",
         "content": "Actionable Suggestions\n- Email Bob\n- Pay rent"},
        {"id": "e2", "type": "DIARY", "date": "2026-06-20", "content": "- not a commitment heading"},
        {"id": "e3", "type": "AUDIO_SUMMARY", "date": "2026-06-19",
         "content": "Discussion notes\nTODO: follow up with Sarah"},
    ]
    out = prod._harvest_commitments(entries)
    # DIARY entry is ignored (only YESTERDAY_RECAP/AUDIO_SUMMARY mined)
    assert out["total"] == 3, out
    assert [c["text"] for c in out["by_date"]["2026-06-20"]] == ["Email Bob", "Pay rent"]
    assert out["by_date"]["2026-06-20"][0]["parsed_section"] is True
    assert out["by_date"]["2026-06-19"][0]["text"] == "follow up with Sarah"
    assert out["by_date"]["2026-06-19"][0]["parsed_section"] is False  # fallback path

def test_tool_wraps_in_envelope():
    async def fake_gather(days):
        return ([{"id": "e1", "type": "YESTERDAY_RECAP", "date": "2026-06-20",
                  "content": "TODOs\n- ship it"}],
                {"calls_used": 1, "days_scanned": days, "capped": None})
    prod._gather_journal_entries = fake_gather  # type: ignore
    out = json.loads(asyncio.run(prod._commitment_harvester_impl(days=7)))
    assert out["data"]["total"] == 1
    assert out["data"]["by_date"]["2026-06-20"][0]["text"] == "ship it"
    assert out["narrative"] is None              # no LLM configured
    assert out["meta"]["calls_used"] == 1 and out["meta"]["days_scanned"] == 7

def main():
    test_harvest_groups_by_date_and_flags()
    test_tool_wraps_in_envelope()
    print("\033[32mPASS\033[0m commitment_harvester")

if __name__ == "__main__":
    main()
