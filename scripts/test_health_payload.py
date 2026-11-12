"""/health payload shape + version single-source tests (OB-69923).

Run: /services/looki-mcp/.venv/bin/python scripts/test_health_payload.py
Offline: imports looki_mcp.server and calls the health handler directly;
no .env, no network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.version import DEPLOYED_AT, GIT_COMMIT, get_version, __version__  # noqa: E402


def _pyproject_version() -> str:
    import tomllib

    data = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    return data["project"]["version"]


def test_version_single_source():
    # helper resolves; /health + FastMCP consumers see the same string
    assert get_version() == __version__
    assert isinstance(__version__, str) and __version__
    # no hardcoded release version: resolved value tracks pyproject.toml
    # (metadata-first in an installed tree, pyproject in the service checkout)
    assert __version__ == _pyproject_version(), (
        f"version {__version__!r} != pyproject {_pyproject_version()!r}"
    )
    assert __version__ != "1.1.0", "stale hardcoded 1.1.0 must be gone"


def test_health_payload_shape():
    import json

    from looki_mcp.server import TOOL_COUNT, health, mcp

    async def _call():
        resp = await health(request=None)  # type: ignore[arg-type]
        return json.loads(resp.body.decode())

    body = asyncio.run(_call())
    for key in ("status", "server", "version", "tools", "git_commit"):
        assert key in body, f"missing key {key}"
    assert body["status"] == "ok"
    assert body["server"] == "looki-mcp"
    assert body["version"] == __version__
    assert body["tools"] == TOOL_COUNT == 30
    # git_commit is present-or-null (null in a dev checkout without .deployed-sha)
    assert body["git_commit"] == GIT_COMMIT
    assert body["git_commit"] is None or (
        isinstance(body["git_commit"], str) and len(body["git_commit"]) >= 7
    )
    # FastMCP constructor carries the same single-sourced version
    assert mcp.version == __version__
    assert DEPLOYED_AT is None or isinstance(DEPLOYED_AT, str)


def main() -> None:
    test_version_single_source()
    test_health_payload_shape()
    print("\033[32mPASS /health payload shape (OB-69923) version=" + __version__ + "\033[0m")


if __name__ == "__main__":
    main()
