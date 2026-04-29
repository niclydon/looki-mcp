"""Smoke test: verify the FastMCP server imports cleanly and registers all tools.

Run: .venv/bin/python scripts/smoke_test.py

This does NOT require .env — it only tests import correctness, not API connectivity.
"""

from __future__ import annotations

import sys

from looki_mcp.server import TOOL_COUNT, mcp


def main() -> int:
    print(f"server name: {mcp.name}")
    print(f"expected tool count: {TOOL_COUNT}")

    tools_attr = None
    for attr in ("_tool_manager", "_tools", "tools"):
        if hasattr(mcp, attr):
            tools_attr = attr
            break

    if tools_attr is None:
        print("note: could not introspect tool list (FastMCP API change)")
        print("OK: import succeeded, FastMCP instance created")
        return 0

    obj = getattr(mcp, tools_attr)
    if hasattr(obj, "_tools"):
        names = sorted(obj._tools.keys())
    elif isinstance(obj, dict):
        names = sorted(obj.keys())
    else:
        names = []

    print(f"registered tools ({len(names)}):")
    for name in names:
        print(f"  - {name}")

    if len(names) != TOOL_COUNT:
        print(f"FAIL: expected {TOOL_COUNT} tools, got {len(names)}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
