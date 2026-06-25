"""Tests for client.governed_get: 429 Retry-After backoff. No real network/sleep.
Run: .venv/bin/python scripts/test_governed_get.py
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import looki_mcp.client as client_mod  # noqa: E402

async def _run(handler):
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as c:
        return await client_mod.governed_get(c, "/moments", params={"on_date": "2026-06-01"})

def test_retries_then_succeeds(monkeypatch_sleep):
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"code": 429, "detail": "rate"})
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": []})
    resp = asyncio.run(_run(handler))
    assert resp.status_code == 200 and calls["n"] == 2

def main():
    # Patch BOTH sleeps (governor + backoff) to no-op for an instant test.
    import looki_mcp.insight.governor as gov
    async def _nosleep(*a, **k): return None
    orig = asyncio.sleep
    asyncio.sleep = _nosleep  # type: ignore
    try:
        test_retries_then_succeeds(None)
    finally:
        asyncio.sleep = orig  # type: ignore
    print("\033[32mPASS\033[0m governed_get")

if __name__ == "__main__":
    main()
