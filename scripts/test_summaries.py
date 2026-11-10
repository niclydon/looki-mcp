"""Tests for get_summaries (OB-69895). No Looki credentials/network needed.

The mock handler reproduces the verified upstream range contract: spans
longer than 7 days are rejected with HTTP 400, envelope code 100.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools import summaries  # noqa: E402

LONG_TEXT = "y" * 4000


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

    saved = (summaries.governed_get, summaries.get_client)
    summaries.governed_get = governed_get
    summaries.get_client = fake_client
    try:
        mcp = _FakeMCP()
        summaries.register_summaries_tools(mcp)
        return asyncio.run(invoke(mcp.tools))
    finally:
        summaries.governed_get, summaries.get_client = saved


def main() -> int:
    calls = []

    def handler(request):
        assert request.url.path == "/summaries"
        params = dict(request.url.params)
        calls.append(params)
        # The param-name trap: only start_date/end_date are acceptable.
        assert "start_date" in params and "end_date" in params, params
        assert "date" not in params and "from_date" not in params, params
        start = datetime.strptime(params["start_date"], "%Y-%m-%d")
        end = datetime.strptime(params["end_date"], "%Y-%m-%d")
        if (end - start).days + 1 > 7:
            return httpx.Response(400, json={"code": 100, "detail": "range too long", "data": None})
        items = []
        cur = start
        while cur <= end:
            items.append({"on_date": cur.strftime("%Y-%m-%d"), "summary": LONG_TEXT})
            cur += timedelta(days=1)
        return httpx.Response(200, json={
            "code": 0, "detail": "ok",
            "data": {"type": params["type"], "items": items},
        })

    async def two_weeks(tools):
        return await tools["get_summaries"]("2026-11-02", "2026-11-15", "daily")

    out = json.loads(_run_tool(handler, two_weeks))
    assert out["type"] == "daily"
    assert len(calls) == 2, calls  # two adjacent 7-day windows
    assert calls[0] == {"start_date": "2026-11-02", "end_date": "2026-11-08", "type": "daily"}
    assert calls[1] == {"start_date": "2026-11-09", "end_date": "2026-11-15", "type": "daily"}
    assert len(out["items"]) == 14
    assert out["items"][0]["summary"] == LONG_TEXT  # full text, never truncated

    async def one_day(tools):
        return await tools["get_summaries"]("2026-11-08", "2026-11-08", "weekly")

    calls.clear()
    out1 = json.loads(_run_tool(handler, one_day))
    assert len(calls) == 1 and len(out1["items"]) == 1

    async def bad_type(tools):
        return await tools["get_summaries"]("2026-11-08", "2026-11-08", "DAILY")

    calls.clear()
    err = _run_tool(handler, bad_type)
    assert err.startswith("Error:") and "daily, weekly, chat, moment" in err, err
    assert calls == [], calls  # rejected client-side, no upstream call

    async def bad_range(tools):
        return await tools["get_summaries"]("2026-11-09", "2026-11-08", "daily")

    assert _run_tool(handler, bad_range).startswith("Error:")

    print("PASS summaries tool (7-day windowing, exact param names, full text, client-side type validation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
