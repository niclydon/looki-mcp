"""FastMCP server instance: registers all tools, custom routes for health and logo."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from starlette.responses import FileResponse, JSONResponse

from looki_mcp.tools.convenience import register_convenience_tools
from looki_mcp.tools.highlights import register_highlights_tools
from looki_mcp.tools.moments import register_moments_tools
from looki_mcp.tools.profile import register_profile_tools
from looki_mcp.tools.realtime import register_realtime_tools

TOOL_COUNT = 12

ASSETS_DIR = Path(__file__).parent.parent / "assets"

mcp = FastMCP(
    name="looki-mcp",
    instructions=(
        "This server provides access to the user's Looki wearable camera memories. "
        "Use search_moments for natural language queries about specific memories. "
        "Use get_moments_calendar or get_recent_activity for activity overview. "
        "Use get_todays_moments for what happened today. "
        "Use get_highlights for AI-generated content (comics, vlogs). "
        "Use get_realtime_event to check what the user is doing right now (requires Proactive Mode)."
    ),
)

register_profile_tools(mcp)
register_moments_tools(mcp)
register_highlights_tools(mcp)
register_realtime_tools(mcp)
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
