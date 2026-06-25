"""Tests for places_of_my_life: pure ranking + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_places_of_my_life.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.tools.insight_places as places  # noqa: E402

def _m(mid, date, loc, start, end, title="t"):
    return {"id": mid, "date": date, "title": title,
            "start_time": f"{date}T{start}+00:00", "end_time": f"{date}T{end}+00:00",
            "cover_file": {"location": loc}}

def test_rank_by_visits_then_time():
    moments = [
        _m("1", "2026-06-01", "Home", "08:00:00", "08:30:00"),
        _m("2", "2026-06-02", "Home", "09:00:00", "10:00:00"),
        _m("3", "2026-06-02", "Cafe", "12:00:00", "13:00:00"),
        _m("4", "2026-06-03", None, "14:00:00", "14:10:00"),   # unknown location
    ]
    out = places._rank_places(moments, top_n=10)
    assert out["unknown_count"] == 1 and out["total_moments"] == 4
    names = [(p["name"], p["visits"]) for p in out["places"]]
    assert names[0] == ("Home", 2), names         # Home has 2 visits, ranks first
    assert ("Cafe", 1) in names
    home = next(p for p in out["places"] if p["name"] == "Home")
    assert home["total_seconds"] == 1800 + 3600    # 30min + 60min
    assert home["sample_moment"]["id"] == "1"

def test_top_n_truncates():
    moments = [_m(str(i), "2026-06-01", f"place{i}", "08:00:00", "08:10:00") for i in range(5)]
    out = places._rank_places(moments, top_n=3)
    assert len(out["places"]) == 3

def test_tool_envelope():
    async def fake_gather(days, deep):
        return ([_m("1", "2026-06-01", "Home", "08:00:00", "08:30:00")],
                {"calls_used": 1, "days_scanned": days, "capped": None})
    places._gather_place_moments = fake_gather  # type: ignore
    saved = places.llm.llm_configured
    places.llm.llm_configured = lambda: False
    try:
        out = json.loads(asyncio.run(places._places_of_my_life_impl(days=30, top_n=15, deep=False)))
    finally:
        places.llm.llm_configured = saved
    assert out["data"]["places"][0]["name"] == "Home"
    assert out["narrative"] is None and out["meta"]["days_scanned"] == 30

def main():
    test_rank_by_visits_then_time(); test_top_n_truncates(); test_tool_envelope()
    print("\033[32mPASS\033[0m places_of_my_life")

if __name__ == "__main__":
    main()
