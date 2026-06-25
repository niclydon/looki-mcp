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

def test_walk_journals_chunks_and_caps():
    call_count = [0]
    def handler(request):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: return items with has_more=true and a date cursor
            return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":[10,20],"next_cursor_id":"2026-06-15","has_more":True}})
        else:
            # Subsequent calls: return more items with has_more=false
            return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":[30,40,50],"next_cursor_id":None,"has_more":False}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x") as c:
            # Non-capped: should fetch both pages
            full = await scan.walk_journals(c, cursor_date=None, max_days=40, max_calls=10)

            # Reset for capped test
            call_count[0] = 0

            # Capped: should stop after 1 call
            capped = await scan.walk_journals(c, cursor_date=None, max_days=40, max_calls=1)
            return full, capped

    full, capped = asyncio.run(run())
    assert full["items"] == [10,20,30,40,50], f"Expected all items, got {full['items']}"
    assert full["calls_used"] == 2, f"Expected 2 calls, got {full['calls_used']}"
    assert full["capped"] is None, f"Expected no capping, got {full['capped']}"

    assert capped["items"] == [10,20], f"Expected capped items from first call, got {capped['items']}"
    assert capped["calls_used"] == 1, f"Expected 1 call when capped, got {capped['calls_used']}"
    assert capped["capped"] == "budget", f"Expected capped='budget', got {capped['capped']}"

def test_page_search_paginates_and_caps():
    call_count = [0]
    def handler(request):
        call_count[0] += 1
        page = int(request.url.params.get("page", 1))
        if page == 1:
            return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":[100,101],"next_cursor_id":None,"has_more":True}})
        elif page == 2:
            return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":[102,103],"next_cursor_id":None,"has_more":True}})
        else:
            # page 3
            return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":[104,105],"next_cursor_id":None,"has_more":False}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x") as c:
            # Non-capped: should fetch all 3 pages
            full = await scan.page_search(c, "test_query", max_pages=10)

            # Reset for capped test
            call_count[0] = 0

            # Capped: should stop after 2 calls (pages)
            capped = await scan.page_search(c, "test_query", max_pages=2)
            return full, capped

    full, capped = asyncio.run(run())
    assert full["items"] == [100,101,102,103,104,105], f"Expected all items, got {full['items']}"
    assert full["calls_used"] == 3, f"Expected 3 calls, got {full['calls_used']}"
    assert full["capped"] is None, f"Expected no capping, got {full['capped']}"

    assert capped["items"] == [100,101,102,103], f"Expected first 2 pages, got {capped['items']}"
    assert capped["calls_used"] == 2, f"Expected 2 calls when capped, got {capped['calls_used']}"
    assert capped["capped"] == "budget", f"Expected capped='budget', got {capped['capped']}"

def main():
    import asyncio as _a
    orig = _a.sleep
    async def _nosleep(*a, **k): return None
    _a.sleep = _nosleep  # type: ignore
    try:
        test_iter_dates_inclusive()
        test_walk_files_paginates_and_caps()
        test_walk_journals_chunks_and_caps()
        test_page_search_paginates_and_caps()
    finally:
        _a.sleep = orig  # type: ignore
    print("\033[32mPASS\033[0m insight.scan")

if __name__ == "__main__":
    main()
