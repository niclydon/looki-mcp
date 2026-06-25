"""Process-lifetime memo cache for deep insight tools, keyed on the RESOLVED window.

Keying on a relative arg (days=30) would serve a stale window tomorrow, so keys
embed today_local + params. In-process dict is the always-on layer (survives across
tool calls within one server process); an object-store layer is added when MinIO is
configured (reuse storage.py). `_now` is injectable for TTL tests.
"""
from __future__ import annotations
import time
from typing import Any

_MEM: dict[str, dict] = {}
_now = time.time


def window_key(tool: str, *, today_local: str, **params) -> str:
    parts = [tool, f"today={today_local}"] + [f"{k}={params[k]}" for k in sorted(params)]
    return "|".join(parts)


async def cache_get(key: str, *, ttl_seconds: float) -> Any | None:
    entry = _MEM.get(key)
    if entry is None:
        return None
    if _now() - entry["_built_at"] > ttl_seconds:
        _MEM.pop(key, None)
        return None
    return entry["value"]


async def cache_put(key: str, value: Any) -> None:
    _MEM[key] = {"value": value, "_built_at": _now()}
