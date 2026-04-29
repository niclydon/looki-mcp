"""Integration test: call get_profile against a running looki-mcp via the MCP protocol.

Requires the server to be running on http://localhost:3456/mcp.
Uses fastmcp's client which handles MCP session initialization.

Run: .venv/bin/python scripts/integration_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client


async def main() -> int:
    url = "http://localhost:3456/mcp"
    print(f"Connecting to {url} ...")
    try:
        async with Client(url) as client:
            tools = await client.list_tools()
            print(f"Server reports {len(tools)} tools")

            print("\nCalling get_profile...")
            result = await client.call_tool("get_profile", {})
            text = result.content[0].text if result.content else ""
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "first_name" in parsed:
                    print(f"PASS: profile returned for {parsed.get('first_name')} {parsed.get('last_name')}")
                    print(f"  email: {parsed.get('email')}")
                    print(f"  tz:    {parsed.get('tz')}")
                    return 0
                if text.startswith("Error:"):
                    print(f"FAIL: tool returned error: {text}")
                    return 1
                print(f"PARTIAL: got response but unexpected shape: {text[:200]}")
                return 1
            except json.JSONDecodeError:
                print(f"FAIL: response was not JSON: {text[:200]}")
                return 1
    except Exception as exc:
        print(f"FAIL: connection error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
