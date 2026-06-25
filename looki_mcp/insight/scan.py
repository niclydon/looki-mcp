"""Per-shape API window walkers. The Looki endpoints do NOT share a pagination
contract (bare lists with no cursor; /files uses cursor_id; /journals uses a DATE
cursor capped at 31 days/call; /search is page-based). So this exposes one walker
PER shape rather than a single leaky abstraction. Every networked walk routes
through client.governed_get (rate governor + 429 backoff) and reports calls_used
+ capped ("budget" when max_calls is hit).
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any

import httpx

from looki_mcp.client import governed_get, unwrap


def iter_dates(start: str, end: str) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    out, d = [], d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


async def walk_files(client: httpx.AsyncClient, moment_id: str, *, max_calls: int) -> dict:
    items: list[Any] = []
    cursor, calls, capped = None, 0, None
    while True:
        if calls >= max_calls:
            capped = "budget"
            break
        params = {"limit": 100}
        if cursor:
            params["cursor_id"] = cursor
        resp = await governed_get(client, f"/moments/{moment_id}/files", params=params)
        calls += 1
        data = unwrap(resp) or {}
        items.extend(data.get("items", []) if isinstance(data, dict) else [])
        cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
        if not (isinstance(data, dict) and data.get("has_more") and cursor):
            break
    return {"items": items, "calls_used": calls, "capped": capped}


async def walk_journals(client: httpx.AsyncClient, *, cursor_date: str | None, max_days: int, max_calls: int) -> dict:
    items: list[Any] = []
    cursor, calls, capped, remaining = cursor_date, 0, None, max_days
    while remaining > 0:
        if calls >= max_calls:
            capped = "budget"
            break
        chunk = min(31, remaining)
        params = {"max_days": chunk}
        if cursor:
            params["cursor_date"] = cursor
        resp = await governed_get(client, "/journals", params=params)
        calls += 1
        data = unwrap(resp) or {}
        items.extend(data.get("items", []) if isinstance(data, dict) else [])
        remaining -= chunk
        cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
        if not (isinstance(data, dict) and data.get("has_more") and cursor):
            break
    return {"items": items, "calls_used": calls, "capped": capped}


async def page_search(client: httpx.AsyncClient, query: str, *, start_date: str | None = None,
                      end_date: str | None = None, max_pages: int, page_size: int = 20) -> dict:
    items: list[Any] = []
    page, calls, capped = 1, 0, None
    while True:
        if calls >= max_pages:
            capped = "budget"
            break
        params: dict = {"query": query, "page": page, "page_size": page_size}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = await governed_get(client, "/moments/search", params=params)
        calls += 1
        data = unwrap(resp) or {}
        items.extend(data.get("items", []) if isinstance(data, dict) else [])
        if not (isinstance(data, dict) and data.get("has_more")):
            break
        page += 1
    return {"items": items, "calls_used": calls, "capped": capped}
