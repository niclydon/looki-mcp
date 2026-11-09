"""Tests for the bounded /journals date scan and the by-date tools. No Looki credentials/network needed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools import journals  # noqa: E402


def _page(days: list[str], *, cursor: str | None, has_more: bool) -> dict:
    return {
        "code": 0,
        "detail": "ok",
        "data": {
            "items": [
                {
                    "date": day,
                    "journals": [{"id": f"id-{day}", "date": day, "type": "DIARY"}],
                }
                for day in days
            ],
            "next_cursor_id": cursor,
            "has_more": has_more,
        },
    }


def _run(handler, target: str):
    async def governed_get(client, url, *, params=None):
        return await client.get(url, params=params)

    original = journals.governed_get
    journals.governed_get = governed_get

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://looki.test"
        ) as client:
            return await journals._journals_for_date(client, target)

    try:
        return asyncio.run(run())
    finally:
        journals.governed_get = original


class _FakeMCP:
    """Captures @mcp.tool registrations so tools can be invoked directly."""

    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def _run_tool(handler, invoke):
    async def governed_get(client, url, *, params=None):
        return await client.get(url, params=params)

    @contextlib.asynccontextmanager
    async def fake_client():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://looki.test"
        ) as client:
            yield client

    saved = (
        journals.governed_get,
        journals.get_client,
        journals.get_config,
        journals._today_local,
        journals._today_utc,
    )
    journals.governed_get = governed_get
    journals.get_client = fake_client
    journals.get_config = lambda: SimpleNamespace(user_timezone=None)
    journals._today_local = lambda: "2026-11-09"
    journals._today_utc = lambda: "2026-11-09"
    try:
        mcp = _FakeMCP()
        journals.register_journals_tools(mcp)
        return asyncio.run(invoke(mcp.tools))
    finally:
        (
            journals.governed_get,
            journals.get_client,
            journals.get_config,
            journals._today_local,
            journals._today_utc,
        ) = saved


def main() -> int:
    def present(request):
        assert request.url.path == "/journals"
        return httpx.Response(200, json=_page(["2026-11-09", "2026-11-08"], cursor="2026-11-07", has_more=True))

    buckets, pages, capped = _run(present, "2026-11-08")
    assert pages == 1 and not capped
    assert [e["id"] for b in buckets for e in b["journals"]] == ["id-2026-11-08"]

    responses = iter([
        _page(["2026-11-09", "2026-11-08"], cursor="2026-11-07", has_more=True),
        _page(["2026-11-07", "2026-11-06"], cursor="2026-11-05", has_more=True),
    ])

    def older(request):
        return httpx.Response(200, json=next(responses))

    buckets, pages, capped = _run(older, "2026-11-06")
    assert pages == 2 and not capped
    assert [e["id"] for b in buckets for e in b["journals"]] == ["id-2026-11-06"]

    def absent(request):
        return httpx.Response(200, json=_page(["2026-11-09", "2026-11-07"], cursor="2026-11-06", has_more=True))

    buckets, pages, capped = _run(absent, "2026-11-08")
    assert buckets == [] and pages == 1 and not capped

    seen_cursors: list[str | None] = []

    def capped_page(request):
        cursor = request.url.params.get("cursor_date")
        seen_cursors.append(cursor)
        page = int(cursor.rsplit("-", 1)[1]) if cursor else 0
        return httpx.Response(200, json=_page([f"2026-10-{31-page:02d}"], cursor=f"cursor-{page+1}", has_more=True))

    buckets, pages, capped = _run(capped_page, "2020-01-01")
    assert buckets == [] and pages == journals._DATE_SCAN_MAX_PAGES and capped
    assert seen_cursors == [None] + [f"cursor-{i}" for i in range(1, journals._DATE_SCAN_MAX_PAGES)]

    def stuck_cursor(request):
        return httpx.Response(200, json=_page(["2026-11-09", "2026-11-08"], cursor="2026-11-07", has_more=True))

    buckets, pages, capped = _run(stuck_cursor, "2026-11-06")
    assert buckets == [] and pages == 2 and not capped

    # normalize_date: unpadded month/day canonicalize; anything else is rejected.
    assert journals.normalize_date("2026-11-09") == "2026-11-09"
    assert journals.normalize_date("2026-11-9") == "2026-11-09"
    assert journals.normalize_date("2026-1-8") == "2026-01-08"
    for bad in ["2026-02-30", "2026-13-01", "2026/11/09", "20261109", "not-a-date", "", None, 20261109]:
        assert journals.normalize_date(bad) is None, bad

    def feed(request):
        return httpx.Response(200, json=_page(["2026-11-09", "2026-11-08"], cursor="2026-11-07", has_more=True))

    async def by_date(tools):
        unpadded = json.loads(await tools["get_journals_by_date"]("2026-11-8"))
        canonical = json.loads(await tools["get_journals_by_date"]("2026-11-08"))
        invalid = await tools["get_journals_by_date"]("2026-02-30")
        return unpadded, canonical, invalid

    unpadded, canonical, invalid = _run_tool(feed, by_date)
    assert unpadded["date"] == "2026-11-08" and unpadded["entry_count"] == 1
    assert canonical["date"] == "2026-11-08" and canonical["entry_count"] == 1
    assert invalid == "Error: date must be in YYYY-MM-DD format."

    def today_feed(request):
        return httpx.Response(200, json={
            "code": 0,
            "detail": "ok",
            "data": {
                "items": [{
                    "date": "2026-11-09",
                    "journals": [
                        {"id": "diary-1", "date": "2026-11-09", "type": "DIARY"},
                        {"id": "recap-1", "date": "2026-11-09", "type": "YESTERDAY_RECAP"},
                    ],
                }],
                "next_cursor_id": "2026-11-08",
                "has_more": True,
            },
        })

    async def todays(tools):
        return json.loads(await tools["get_todays_journal"]())

    out = _run_tool(today_feed, todays)
    assert out["date_local"] == "2026-11-09" and out["entry_count"] == 2
    assert [e["id"] for e in out["entries"]] == ["recap-1", "diary-1"]

    print("PASS journals by-date scan + tools (present, multi-page, absent, bounded, stuck cursor, normalize, by-date, today)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
