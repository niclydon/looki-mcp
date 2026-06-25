"""Unit tests for the insight rate governor (injected clock, no real sleep).
Run: .venv/bin/python scripts/test_governor.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.insight.governor import RateGovernor  # noqa: E402

def test_first_calls_are_free_then_throttle():
    t = [0.0]
    g = RateGovernor(rate_per_min=60.0, now=lambda: t[0])  # 1 token/sec, burst=capacity
    # Drain the full burst capacity (capacity == rate by default) with no wait.
    waits = [g._take() for _ in range(60)]
    assert all(w == 0 for w in waits), f"burst should be free, got {waits[:5]}"
    # 61st call in the same instant must wait ~1s for the next token.
    w = g._take()
    assert 0.9 <= w <= 1.1, f"expected ~1s wait, got {w}"

def test_tokens_refill_over_time():
    t = [0.0]
    g = RateGovernor(rate_per_min=60.0, now=lambda: t[0])
    for _ in range(60):
        g._take()
    t[0] = 5.0  # 5 seconds later -> ~5 tokens refilled
    waits = [g._take() for _ in range(5)]
    assert all(w == 0 for w in waits), f"refilled tokens should be free, got {waits}"
    assert g._take() > 0, "6th after 5s refill should throttle"

def main():
    test_first_calls_are_free_then_throttle()
    test_tokens_refill_over_time()
    print("\033[32mPASS\033[0m governor")

if __name__ == "__main__":
    main()
