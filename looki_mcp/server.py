"""FastMCP server instance: registers all tools, custom routes for health and logo."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
import tomllib
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import Icon
from starlette.responses import FileResponse, JSONResponse

from looki_mcp.tools.chat import register_chat_tools
from looki_mcp.tools.composites import register_composite_tools
from looki_mcp.tools.convenience import register_convenience_tools
from looki_mcp.tools.highlights import register_highlights_tools
from looki_mcp.tools.health import register_health_tools
from looki_mcp.tools.insight_memory import register_insight_memory_tools
from looki_mcp.tools.insight_places import register_places_tools
from looki_mcp.tools.insight_productivity import register_productivity_tools
from looki_mcp.tools.journals import register_journals_tools
from looki_mcp.tools.memory import register_memory_tools
from looki_mcp.tools.moments import register_moments_tools
from looki_mcp.tools.profile import register_profile_tools
from looki_mcp.tools.realtime import register_realtime_tools
from looki_mcp.tools.summaries import register_summaries_tools
from looki_mcp.tools.video import register_video_tools

# Fallback tool count (asserted by scripts/smoke_test.py); /health reports the
# live registered count and only falls back to this if listing fails.
TOOL_COUNT = 33

# Single source of truth for the version is pyproject.toml. The service runs
# from a source checkout (scripts/deploy.sh) or a container that copies
# pyproject.toml, and the package is never pip-installed there, so the file is
# read first; installed distribution metadata is only a fallback for a wheel
# install without the file, so a stale installed copy can never win. There is
# no version literal in code.
def _resolve_version() -> str:
    try:
        with open(Path(__file__).resolve().parent.parent / "pyproject.toml", "rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return _dist_version("looki-mcp")
    except PackageNotFoundError:
        return "unknown"


__version__ = _resolve_version()

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
    version=__version__,
    website_url="https://web.looki.ai",
    icons=_icons,
    instructions=(
        "This server provides access to the user's Looki wearable camera memories. "
        "Use get_memory_overview for the user's consolidated Looki context summary "
        "(identity, lifestyle, traits, relationships, current experiences). "
        "Use get_summaries for Looki life summaries (daily, weekly, chat, moment) over a date range. "
        "Use get_health_reports for Looki daily health reports (diet, activity metrics, sleep-adjacent estimates) over a date range. "
        "Use get_chat_history for the user's past conversations with the Looki assistant. "
        "Use search_moments for natural language queries about specific memories. "
        "Use get_moments_calendar or get_recent_activity for activity overview. "
        "Use get_todays_moments for what happened today. "
        "Use get_highlights for AI-generated content (comics, vlogs). "
        "Use get_recent_journals, get_todays_journal, or search_journals for the user's written journal — "
        "AI-generated diary recaps, dietary and meeting summaries, and storyboards; "
        "get_journal_entry reads one entry in full and backfill_journals loads deep history. "
        "Journal images are AI-generated and their URLs expire quickly; capture_journal_media and "
        "backfill_journal_media save durable copies to object storage (get_journal_entry also captures on read). "
        "Use get_realtime_event or describe_realtime_event to check what the user is doing right now (requires Proactive Mode; describe adds optional Forge VLM snapshot caption when available)."
        " Insight tools (commitment_harvester, the_unwritten, places_of_my_life) "
        "combine multiple endpoints and return a {data, narrative, meta} envelope "
        "(narrative is filled only when an LLM provider is configured)."
    ),
)

register_profile_tools(mcp)
register_memory_tools(mcp)
register_summaries_tools(mcp)
register_health_tools(mcp)
register_chat_tools(mcp)
register_composite_tools(mcp)
register_moments_tools(mcp)
register_highlights_tools(mcp)
register_journals_tools(mcp)
register_realtime_tools(mcp)
register_video_tools(mcp)
register_convenience_tools(mcp)
register_productivity_tools(mcp)
register_insight_memory_tools(mcp)
register_places_tools(mcp)


SERVICE_ROOT = Path(__file__).parent.parent
DEPLOYED_SHA_PATH = SERVICE_ROOT / ".deployed-sha"


def _deploy_stamp() -> tuple[str, str]:
    """Return (commit, deployed_at) for /health.

    scripts/deploy.sh writes the deployed SHA to .deployed-sha at the service
    root; its mtime is the deploy time. Read on every call, so a redeploy
    shows without a restart. LOOKI_MCP_COMMIT overrides the commit (e.g.
    container builds). Mirrors looki-mcp-worker's git_commit/deployed_at.

    The pair always describes one deploy: deployed_at is the file's mtime only
    when the commit came from that same file and is non-empty; an env-sourced
    commit reports deployed_at "unknown", and an absent or empty stamp
    reports both "unknown".
    """
    env_commit = os.environ.get("LOOKI_MCP_COMMIT", "").strip()
    if env_commit:
        return env_commit, "unknown"
    try:
        st = DEPLOYED_SHA_PATH.stat()
        commit = DEPLOYED_SHA_PATH.read_text().strip()
    except OSError:
        return "unknown", "unknown"
    if not commit:
        return "unknown", "unknown"
    deployed_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return commit, deployed_at


@mcp.custom_route("/health", methods=["GET"])
async def health(request) -> JSONResponse:  # type: ignore[no-untyped-def]
    try:
        tool_count = len(await mcp._list_tools())
    except Exception:  # noqa: BLE001 - health must not fail on introspection
        tool_count = TOOL_COUNT
    commit, deployed_at = _deploy_stamp()
    return JSONResponse(
        {
            "status": "ok",
            "server": "looki-mcp",
            "version": __version__,
            "tools": tool_count,
            "git_commit": commit,
            "deployed_at": deployed_at,
        }
    )


@mcp.custom_route("/logo.ico", methods=["GET"])
async def logo(request) -> FileResponse | JSONResponse:  # type: ignore[no-untyped-def]
    logo_path = ASSETS_DIR / "looki-logo.ico"
    if not logo_path.exists():
        return JSONResponse({"error": "logo not found"}, status_code=404)
    return FileResponse(str(logo_path), media_type="image/x-icon")
