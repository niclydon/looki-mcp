"""Verify get_moment_files forwards the Looki cursor using its wire name."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools import moments  # noqa: E402


class _Response:
    def raise_for_status(self):
        pass

    def json(self):
        return {"code": 0, "detail": "ok", "data": {"items": []}}


class _Client:
    def __init__(self):
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, path, params=None):
        self.request = (path, params)
        return _Response()


class _Mcp:
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def main() -> int:
    client = _Client()
    moments.get_client = lambda: client
    mcp = _Mcp()
    moments.register_moments_tools(mcp)

    result = asyncio.run(mcp.tools["get_moment_files"]("moment-123", cursor_id="page-2"))
    assert json.loads(result) == {"items": []}
    assert client.request == (
        "/moments/moment-123/files",
        {"limit": 20, "cursor": "page-2"},
    )
    assert "cursor_id" not in client.request[1]
    print("PASS get_moment_files sends cursor query parameter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
