"""Tests for insight.cache in-process layer + window keys. Run: .venv/bin/python scripts/test_cache.py"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.insight.cache as cache  # noqa: E402

def test_window_key_includes_resolved_window():
    k1 = cache.window_key("places_of_my_life", today_local="2026-06-24", days=30)
    k2 = cache.window_key("places_of_my_life", today_local="2026-07-10", days=30)
    assert k1 != k2, "same days arg on different days must yield different keys"

def test_put_get_and_ttl():
    t = [100.0]
    cache._now = lambda: t[0]  # type: ignore
    cache._MEM.clear()
    asyncio.run(cache.cache_put("k", {"v": 1}))
    assert asyncio.run(cache.cache_get("k", ttl_seconds=60)) == {"v": 1}
    t[0] = 100.0 + 61
    assert asyncio.run(cache.cache_get("k", ttl_seconds=60)) is None  # expired

def main():
    test_window_key_includes_resolved_window(); test_put_get_and_ttl()
    print("\033[32mPASS\033[0m insight.cache")

if __name__ == "__main__":
    main()
