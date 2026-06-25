"""Characterization test for the refactored describe_realtime_event.
Run: .venv/bin/python scripts/test_realtime_describe.py"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.insight.llm as llm  # noqa: E402
from fastmcp import FastMCP  # noqa: E402
from looki_mcp.tools.realtime import register_realtime_tools  # noqa: E402

class _FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): return None
    def json(self): return {"code": 0, "detail": "ok", "data": self._p}

def _get_tool(fn_name):
    mcp = FastMCP(name="t")
    register_realtime_tools(mcp)
    return mcp  # tools registered; we call the underlying coroutine via the module

async def scenario(caption):
    # Patch the Looki client + the VLM call.
    import looki_mcp.tools.realtime as rt
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _FakeResp({"description":"walking","file":{"temporary_url":"http://x/s.jpg"}})
    rt.get_client = lambda: _Client()  # type: ignore
    async def fake_desc(url, prompt, **k): return caption
    llm.describe_image = fake_desc  # type: ignore
    # call the tool function directly
    return await rt._describe_realtime_event_impl()

def test_envelope_with_caption():
    out = json.loads(asyncio.run(scenario("a person walking")))
    assert out["data"]["event"]["description"] == "walking"
    assert out["data"]["image_url"] == "http://x/s.jpg"
    assert out["narrative"] == "a person walking"
    assert out["meta"]["vlm_used"] is True

def test_envelope_without_caption():
    out = json.loads(asyncio.run(scenario(None)))
    assert out["narrative"] is None and out["meta"]["vlm_used"] is False

def main():
    test_envelope_with_caption(); test_envelope_without_caption()
    print("\033[32mPASS\033[0m realtime.describe refactor")

if __name__ == "__main__":
    main()
