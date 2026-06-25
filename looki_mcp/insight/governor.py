"""Shared async throughput governor for Looki + VLM calls.

The Looki API enforces 60 req/min as a sliding window (HTTP 429). A call-COUNT
budget cannot prevent that; this token-bucket bounds THROUGHPUT. One process-wide
singleton is shared by every insight tool so concurrent fan-outs (e.g. captioning
N photos) cannot collectively exceed the window.

`now` is injectable so the bucket math is unit-testable without sleeping.
"""
from __future__ import annotations
import asyncio
import time
from contextlib import asynccontextmanager
from typing import Callable


class RateGovernor:
    def __init__(self, rate_per_min: float = 50.0, *, now: Callable[[], float] = time.monotonic) -> None:
        self._rate_per_sec = rate_per_min / 60.0
        self._capacity = rate_per_min          # allow one minute's burst
        self._tokens = float(rate_per_min)
        self._now = now
        self._last = now()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        t = self._now()
        elapsed = max(0.0, t - self._last)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)
        self._last = t

    def _take(self, n: int = 1) -> float:
        """Consume n tokens. Returns seconds to wait before they're available (0 if free now)."""
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return 0.0
        deficit = n - self._tokens
        self._tokens = 0.0
        return deficit / self._rate_per_sec

    @asynccontextmanager
    async def slot(self):
        async with self._lock:
            wait = self._take()
        if wait > 0:
            await asyncio.sleep(wait)
        yield


_governor: RateGovernor | None = None


def get_governor() -> RateGovernor:
    global _governor
    if _governor is None:
        _governor = RateGovernor()
    return _governor
