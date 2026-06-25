"""Asserts server registers TOOL_COUNT tools incl. the 3 PR2 insight tools (no network).
Run: .venv/bin/python scripts/test_tool_count.py

Accessor note: fastmcp 3.2.4 does not have mcp.get_tools(); we use
  await mcp.list_tools() -> Sequence[Tool]  (each item has a .name attr).
The brief's mcp.get_tools() -> dict[name, Tool] pattern is adapted here to
match the installed API while preserving identical assertion logic.
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.server import mcp, TOOL_COUNT  # noqa: E402


def test_count_and_new_tools():
    tool_list = asyncio.run(mcp.list_tools())   # fastmcp 3.2.4: Sequence[Tool]
    names = {t.name for t in tool_list}
    assert len(names) == TOOL_COUNT, (
        f"{len(names)} registered vs TOOL_COUNT={TOOL_COUNT}: {sorted(names)}"
    )
    for t in ("commitment_harvester", "the_unwritten", "places_of_my_life"):
        assert t in names, f"missing {t}"
    assert TOOL_COUNT == 27


def main():
    test_count_and_new_tools()
    print("\033[32mPASS\033[0m tool_count")


if __name__ == "__main__":
    main()
