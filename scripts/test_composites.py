"""Tests for the composite context tools (OB-69898). No credentials/network needed.

Covers section labeling, per-section failure isolation (the health
ingredient is made to fail), and latest-item selection for
get_personal_context.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools import composites, health, journals, summaries  # noqa: E402

LONG_TEXT = "c" * 2000


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def _handler(request):
    path = request.url.path
    params = dict(request.url.params)
    if path == "/moments":
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": [
            {"id": "m1", "title": "Morning", "audio_summary": LONG_TEXT},
        ]})
    if path == "/summaries":
        if params["type"] == "daily":
            items = [{"on_date": params["end_date"], "summary": LONG_TEXT}]
        elif params["type"] == "weekly":
            items = [
                {"on_date": params["start_date"], "summary": "older"},
                {"on_date": params["end_date"], "summary": LONG_TEXT},
            ]
        else:
            items = []
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {"type": params["type"], "items": items}})
    if path == "/health-reports":
        return httpx.Response(500, json={"code": 100, "detail": "boom", "data": None})
    if path == "/journals":
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {
            "items": [{"date": "2026-11-08", "journals": [
                {"id": "j1", "date": "2026-11-08", "type": "DIARY", "content": LONG_TEXT, "media_items": []},
            ]}],
            "next_cursor_id": None, "has_more": False,
        }})
    if path == "/memory/overview":
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {
            "summaries": {"identity": LONG_TEXT}, "updated_at": "2026-11-09T00:00:00Z",
        }})
    return httpx.Response(404, json={"code": 100, "detail": "not found", "data": None})


def _run_tool(invoke):
    async def governed_get(client, url, *, params=None, max_retries=2):
        return await client.get(url, params=params)

    @contextlib.asynccontextmanager
    async def fake_client():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="https://looki.test"
        ) as client:
            yield client

    modules = (composites, summaries, health, journals)
    saved = [(m, m.governed_get) for m in modules]
    for m in modules:
        m.governed_get = governed_get
    saved_client = composites.get_client
    saved_today = composites._today_local
    composites.get_client = fake_client
    composites._today_local = lambda: "2026-11-09"
    try:
        mcp = _FakeMCP()
        composites.register_composite_tools(mcp)
        return asyncio.run(invoke(mcp.tools))
    finally:
        for m, fn in saved:
            m.governed_get = fn
        composites.get_client = saved_client
        composites._today_local = saved_today


def main() -> int:
    async def day(tools):
        return await tools["get_day_context"]("2026-11-08")

    out = json.loads(_run_tool(day))
    assert out["date"] == "2026-11-08"
    secs = out["sections"]
    assert secs["moments"]["source"] == "moments"
    assert secs["moments"]["data"][0]["audio_summary"]["text"] == LONG_TEXT
    assert secs["daily_summary"]["source"] == "summaries:daily"
    assert secs["daily_summary"]["data"][0]["summary"] == LONG_TEXT
    # Failure isolation: health ingredient 500s, its section carries the
    # error and the rest of the call still succeeds.
    assert secs["health_report"]["source"] == "health_reports"
    assert "error" in secs["health_report"], secs["health_report"]
    assert secs["journals"]["source"] == "journals"
    assert secs["journals"]["data"]["entry_count"] == 1
    assert secs["journals"]["data"]["entries"][0]["content"] == LONG_TEXT

    async def personal(tools):
        return await tools["get_personal_context"]()

    out2 = json.loads(_run_tool(personal))
    secs2 = out2["sections"]
    assert secs2["memory_overview"]["data"]["summaries"]["identity"] == LONG_TEXT
    assert secs2["latest_daily_summary"]["data"]["summary"] == LONG_TEXT
    # Latest weekly = the item with the greatest on_date (the window end).
    assert secs2["latest_weekly_summary"]["data"]["summary"] == LONG_TEXT
    assert secs2["latest_weekly_summary"]["data"]["on_date"] == out2["as_of"]

    async def bad_date(tools):
        return await tools["get_day_context"]("not-a-date")

    assert _run_tool(bad_date).startswith("Error:")

    print("PASS composites (labeled sections, failure isolation, latest-item selection, date validation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
