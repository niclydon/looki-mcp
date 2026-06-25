"""Tests for insight.scan walkers. Run: .venv/bin/python scripts/test_scan.py"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import looki_mcp.insight.scan as scan  # noqa: E402

def test_iter_dates_inclusive():
    assert scan.iter_dates("2026-06-01", "2026-06-03") == ["2026-06-01","2026-06-02","2026-06-03"]

def test_walk_files_paginates_and_caps():
    pages = {None: ("c1", [1,2]), "c1": ("c2", [3,4]), "c2": (None, [5])}
    def handler(request):
        cur = request.url.params.get("cursor_id")
        nxt, items = pages[cur]
        return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":items,"next_cursor_id":nxt,"has_more":nxt is not None}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x") as c:
            full = await scan.walk_files(c, "M1", max_calls=10)
            capped = await scan.walk_files(c, "M1", max_calls=2)
            return full, capped
    full, capped = asyncio.run(run())
    assert full["items"] == [1,2,3,4,5] and full["capped"] is None
    assert capped["calls_used"] == 2 and capped["capped"] == "budget"
    assert capped["items"] == [1,2,3,4]

def main():
    import asyncio as _a
    orig = _a.sleep
    async def _nosleep(*a, **k): return None
    _a.sleep = _nosleep  # type: ignore
    try:
        test_iter_dates_inclusive(); test_walk_files_paginates_and_caps()
    finally:
        _a.sleep = orig  # type: ignore
    print("\033[32mPASS\033[0m insight.scan")

if __name__ == "__main__":
    main()
