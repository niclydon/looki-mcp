"""Tests for the bounded /journals date scan. No Looki credentials/network needed."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

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

    def capped_page(request):
        page = int(request.url.params.get("page", 0))
        return httpx.Response(200, json=_page([f"2026-10-{31-page:02d}"], cursor=f"c{page+1}", has_more=True))

    buckets, pages, capped = _run(capped_page, "2020-01-01")
    assert buckets == [] and pages == journals._DATE_SCAN_MAX_PAGES and capped
    print("PASS journals by-date scan (present, multi-page, absent, bounded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
