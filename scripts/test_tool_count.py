"""Asserts the server registers TOOL_COUNT tools incl. the 3 Insight tools (no network).
Run: .venv/bin/python scripts/test_tool_count.py

fastmcp exposes `await mcp.list_tools()` -> Sequence[Tool] (each item has .name).
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.server import mcp, TOOL_COUNT  # noqa: E402


def test_count_and_new_tools():
    tool_list = asyncio.run(mcp.list_tools())
    names = {t.name for t in tool_list}
    assert len(names) == TOOL_COUNT, (
        f"{len(names)} registered vs TOOL_COUNT={TOOL_COUNT}: {sorted(names)}"
    )
    for t in ("commitment_harvester", "the_unwritten", "places_of_my_life"):
        assert t in names, f"missing {t}"
    # Pre-existing memory tool must survive (insight memory registrar is distinct).
    assert "get_memory_overview" in names
    assert TOOL_COUNT == 33


def main():
    test_count_and_new_tools()
    print("\033[32mPASS\033[0m tool_count")


if __name__ == "__main__":
    main()
