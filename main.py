"""Entry point: validate config, then run the FastMCP HTTP server."""

from __future__ import annotations

import asyncio

from looki_mcp.config import Config, load_and_validate_config
from looki_mcp.server import TOOL_COUNT, mcp


async def _startup() -> Config:
    return await load_and_validate_config()


def run() -> None:
    config = asyncio.run(_startup())
    print(f"[looki-mcp] Server running on http://0.0.0.0:{config.port}/mcp ({TOOL_COUNT} tools)", flush=True)
    if config.public_url:
        print(f"[looki-mcp] Public MCP URL: {config.public_url}/mcp", flush=True)
        print(f"[looki-mcp] Icon URL:       {config.public_url}/logo.ico", flush=True)
    else:
        print("[looki-mcp] Tip: Set LOOKI_MCP_BASE_URL to enable icon display in MCP clients", flush=True)
    # show_banner=False suppresses the upstream "Deploy free: prefect.io" ad
    # that FastMCP prints by default on HTTP startup.
    mcp.run(transport="http", host="0.0.0.0", port=config.port, show_banner=False)


if __name__ == "__main__":
    run()
