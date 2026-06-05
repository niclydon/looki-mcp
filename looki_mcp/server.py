"""FastMCP server instance: registers all tools, custom routes for health and logo."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import Icon
from starlette.responses import FileResponse, JSONResponse

from looki_mcp.tools.convenience import register_convenience_tools
from looki_mcp.tools.highlights import register_highlights_tools
from looki_mcp.tools.moments import register_moments_tools
from looki_mcp.tools.profile import register_profile_tools
from looki_mcp.tools.realtime import register_realtime_tools
from looki_mcp.tools.video import register_video_tools

TOOL_COUNT = 14

ASSETS_DIR = Path(__file__).parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "looki-logo.ico"


def _logo_cache_key() -> str:
    """8-char hex hash of the logo bytes — used as ?v= cache buster on the icon URL.

    Changes whenever the logo file changes, stable across restarts otherwise.
    Lets MCP clients (claude.ai etc.) bypass their own caches when we update
    the asset, without forcing the user to re-add the connector.
    """
    if not LOGO_PATH.exists():
        return "0"
    return hashlib.sha256(LOGO_PATH.read_bytes()).hexdigest()[:8]


# We construct the FastMCP instance at import time, before config validation
# runs. So the icon URL is read directly from the env var rather than from the
# loaded Config object — no functional difference, but keeps the import order
# clean. If LOOKI_MCP_BASE_URL is unset, no icons are advertised; clients
# fall back to /favicon.ico from the host.
_PUBLIC_URL = os.environ.get("LOOKI_MCP_BASE_URL", "").strip()
_icons: list[Icon] | None = (
    [Icon(src=f"{_PUBLIC_URL}/logo.ico?v={_logo_cache_key()}", mimeType="image/x-icon")]
    if _PUBLIC_URL
    else None
)

mcp = FastMCP(
    name="looki-mcp",
    version="1.0.0",
    website_url="https://web.looki.ai",
    icons=_icons,
    instructions=(
        "This server provides access to the user's Looki wearable camera memories. "
        "Use search_moments for natural language queries about specific memories. "
        "Use get_moments_calendar or get_recent_activity for activity overview. "
        "Use get_todays_moments for what happened today. "
        "Use get_highlights for AI-generated content (comics, vlogs). "
        "Use get_realtime_event or describe_realtime_event to check what the user is doing right now (requires Proactive Mode; describe adds optional Forge VLM snapshot caption when available)."
    ),
)

register_profile_tools(mcp)
register_moments_tools(mcp)
register_highlights_tools(mcp)
register_realtime_tools(mcp)
register_video_tools(mcp)
register_convenience_tools(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request) -> JSONResponse:  # type: ignore[no-untyped-def]
    return JSONResponse(
        {
            "status": "ok",
            "server": "looki-mcp",
            "version": "1.0.0",
            "tools": TOOL_COUNT,
        }
    )


@mcp.custom_route("/logo.ico", methods=["GET"])
async def logo(request) -> FileResponse | JSONResponse:  # type: ignore[no-untyped-def]
    logo_path = ASSETS_DIR / "looki-logo.ico"
    if not logo_path.exists():
        return JSONResponse({"error": "logo not found"}, status_code=404)
    return FileResponse(str(logo_path), media_type="image/x-icon")
