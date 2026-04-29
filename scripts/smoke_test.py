"""Smoke test: verify the FastMCP server imports cleanly and registers all tools.

Run: .venv/bin/python scripts/smoke_test.py

This does NOT require .env — it only tests import correctness, not API connectivity.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.server import TOOL_COUNT, mcp  # noqa: E402


async def main() -> int:
    print(f"server name: {mcp.name}")
    print(f"expected tool count: {TOOL_COUNT}")

    tools = await mcp._list_tools()
    names = sorted(t.name for t in tools)
    print(f"registered tools ({len(names)}):")
    for name in names:
        print(f"  - {name}")

    if len(names) != TOOL_COUNT:
        print(f"FAIL: expected {TOOL_COUNT} tools, got {len(names)}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
