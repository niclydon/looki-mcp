"""Tests for get_chat_history (OB-69897). No Looki credentials/network needed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools import chat  # noqa: E402

LONG_TEXT = "w" * 3000
ALL_MESSAGES = [
    {"role": "user" if i % 2 == 0 else "assistant", "text": LONG_TEXT, "created_at": f"2026-11-0{1 + i // 3}T10:0{i % 10}:00-05:00"}
    for i in range(5)
]


class _FakeMCP:
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

    saved = (chat.governed_get, chat.get_client)
    chat.governed_get = governed_get
    chat.get_client = fake_client
    try:
        mcp = _FakeMCP()
        chat.register_chat_tools(mcp)
        return asyncio.run(invoke(mcp.tools))
    finally:
        chat.governed_get, chat.get_client = saved


def main() -> int:
    calls = []

    def handler(request):
        assert request.url.path == "/chat/history"
        params = dict(request.url.params)
        calls.append(params)
        limit = int(params.get("limit", "50"))
        # Cursor is an opaque offset token in this mock.
        offset = int(params["cursor"].split("-")[1]) if "cursor" in params else 0
        page = ALL_MESSAGES[offset:offset + limit]
        has_more = offset + limit < len(ALL_MESSAGES)
        return httpx.Response(200, json={
            "code": 0, "detail": "ok",
            "data": {
                "items": page,
                "has_more": has_more,
                "next_cursor": f"cur-{offset + limit}" if has_more else None,
            },
        })

    async def page1(tools):
        return await tools["get_chat_history"](2)

    out = json.loads(_run_tool(handler, page1))
    assert len(out["items"]) == 2 and out["has_more"] is True
    assert out["next_cursor"] == "cur-2"
    assert out["items"][0]["text"] == LONG_TEXT  # full text, never truncated
    assert set(out["items"][0].keys()) == {"role", "text", "created_at"}

    async def page2(tools):
        return await tools["get_chat_history"](2, cursor="cur-2")

    out2 = json.loads(_run_tool(handler, page2))
    assert len(out2["items"]) == 2 and out2["items"][0] == ALL_MESSAGES[2]
    assert calls[-1].get("cursor") == "cur-2"  # passed through opaquely

    async def with_since(tools):
        return await tools["get_chat_history"](5, since="2026-11-01T00:00:00-05:00")

    json.loads(_run_tool(handler, with_since))
    assert calls[-1].get("since") == "2026-11-01T00:00:00-05:00"

    async def bad_limit(tools):
        return await tools["get_chat_history"](0)

    assert _run_tool(handler, bad_limit).startswith("Error:")

    print("PASS chat history tool (cursor passthrough, has_more, since, full text, limit validation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
