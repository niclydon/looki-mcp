"""Tests for get_memory_overview (OB-69894). No Looki credentials/network needed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools import memory  # noqa: E402

SUMMARY_KEYS = {
    "identity",
    "lifestyle",
    "traits",
    "interests",
    "relationships",
    "current_experiences",
    "looki_preferences",
}

LONG_TEXT = "x" * 5000  # must come back in full: Looki content is never truncated


class _FakeMCP:
    """Captures @mcp.tool registrations so tools can be invoked directly."""

    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def _run_tool(handler, invoke):
    async def governed_get(client, url, *, params=None, max_retries=2):
        return await client.get(url, params=params)

    @contextlib.asynccontextmanager
    async def fake_client():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://looki.test"
        ) as client:
            yield client

    saved = (memory.governed_get, memory.get_client)
    memory.governed_get = governed_get
    memory.get_client = fake_client
    try:
        mcp = _FakeMCP()
        memory.register_memory_tools(mcp)
        return asyncio.run(invoke(mcp.tools))
    finally:
        memory.governed_get, memory.get_client = saved


def main() -> int:
    seen_paths = []

    def ok_handler(request):
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={
            "code": 0,
            "detail": "ok",
            "data": {
                "summaries": {k: LONG_TEXT for k in SUMMARY_KEYS},
                "updated_at": "2026-11-09T12:00:00Z",
            },
        })

    async def call(tools):
        return await tools["get_memory_overview"]()

    out = json.loads(_run_tool(ok_handler, call))
    assert seen_paths == ["/memory/overview"], seen_paths
    assert set(out["summaries"].keys()) == SUMMARY_KEYS
    assert out["summaries"]["identity"] == LONG_TEXT
    assert out["updated_at"] == "2026-11-09T12:00:00Z"

    def err_handler(request):
        return httpx.Response(200, json={"code": 105, "detail": "deprecated", "data": None})

    out_err = _run_tool(err_handler, call)
    assert out_err.startswith("Error:"), out_err

    print("PASS memory overview tool (path, summaries keys, full text, updated_at, error surface)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
