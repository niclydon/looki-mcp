"""Tests for get_health_reports (OB-69896). No Looki credentials/network needed.

The mock handler reproduces the verified upstream behavior: a request
returns at most the first 30 days of the requested range (silent
truncation), so correct results over a long range require windowing.
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

from looki_mcp.tools import health  # noqa: E402

REPORT_DATA_KEYS = {"summary", "calorie", "daily_metrics", "dietary_review", "events", "time_range"}
LONG_TEXT = "z" * 3000


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

    saved = (health.governed_get, health.get_client)
    health.governed_get = governed_get
    health.get_client = fake_client
    try:
        mcp = _FakeMCP()
        health.register_health_tools(mcp)
        return asyncio.run(invoke(mcp.tools))
    finally:
        health.governed_get, health.get_client = saved


def main() -> int:
    calls = []

    def handler(request):
        assert request.url.path == "/health-reports"
        params = dict(request.url.params)
        calls.append(params)
        assert "start_date" in params and "end_date" in params, params
        start = datetime.strptime(params["start_date"], "%Y-%m-%d")
        end = datetime.strptime(params["end_date"], "%Y-%m-%d")
        # Upstream silently truncates to the first 30 days of the range.
        last = min(end, start + timedelta(days=29))
        items = []
        cur = start
        while cur <= last:
            items.append({
                "date": cur.strftime("%Y-%m-%d"),
                "tz": "-05:00",
                "report_data": {k: LONG_TEXT for k in REPORT_DATA_KEYS},
            })
            cur += timedelta(days=1)
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": {"items": items}})

    async def long_range(tools):
        return await tools["get_health_reports"]("2026-09-01", "2026-11-08")

    out = json.loads(_run_tool(handler, long_range))
    assert len(calls) == 3, calls  # 30 + 30 + 9 day windows
    assert len(out["items"]) == 69, len(out["items"])  # full range, no silent loss
    dates = [i["date"] for i in out["items"]]
    assert dates[0] == "2026-09-01" and dates[-1] == "2026-11-08"
    assert len(set(dates)) == 69  # no duplicates at window seams
    first = out["items"][0]
    assert set(first["report_data"].keys()) == REPORT_DATA_KEYS
    assert first["report_data"]["summary"] == LONG_TEXT  # full, never truncated
    assert first["tz"] == "-05:00"

    async def one_day(tools):
        return await tools["get_health_reports"]("2026-11-08", "2026-11-08")

    calls.clear()
    out1 = json.loads(_run_tool(handler, one_day))
    assert len(calls) == 1 and len(out1["items"]) == 1

    async def bad_range(tools):
        return await tools["get_health_reports"]("2026-11-09", "2026-11-08")

    assert _run_tool(handler, bad_range).startswith("Error:")

    print("PASS health reports tool (30-day windowing defeats silent truncation, report_data keys, tz preserved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
