"""Offline contract test for moment-file cursor forwarding."""

import asyncio

import httpx

from looki_mcp.tools import moments

class _Mcp:
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def test_get_moment_files_forwards_cursor_and_legacy_cursor_id():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {"items": [], "next_cursor": "next"}})

    original_get_client = moments.get_client
    moments.get_client = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://looki.test"
    )
    try:
        mcp = _Mcp()
        moments.register_moments_tools(mcp)
        tool = mcp.tools["get_moment_files"]

        asyncio.run(tool("moment-1", cursor="from-cursor"))
        asyncio.run(tool("moment-1", cursor_id="from-legacy"))
        asyncio.run(tool("moment-1"))
        conflict = asyncio.run(tool("moment-1", cursor="a", cursor_id="b"))
    finally:
        moments.get_client = original_get_client

    assert requests[0].url.params["cursor"] == "from-cursor"
    assert requests[1].url.params["cursor"] == "from-legacy"
    for request in requests:
        assert "cursor_id" not in request.url.params
    assert "cursor" not in requests[2].url.params
    assert "must match" in conflict


if __name__ == "__main__":
    test_get_moment_files_forwards_cursor_and_legacy_cursor_id()
    print("PASS: moment-files cursor contract")
