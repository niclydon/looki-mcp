"""Tests for the /health payload. Run: .venv/bin/python scripts/test_health_endpoint.py"""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOOKI_API_KEY", "test")
from starlette.testclient import TestClient  # noqa: E402
import looki_mcp.server as server  # noqa: E402


def _get() -> dict:
    with TestClient(server.mcp.http_app()) as c:
        r = c.get("/health")
        assert r.status_code == 200
        return r.json()


def test_payload_keys_and_version():
    server.DEPLOYED_SHA_PATH = Path("/nonexistent/.deployed-sha")
    os.environ.pop("LOOKI_MCP_COMMIT", None)
    body = _get()
    assert set(body) == {"status", "server", "version", "tools", "commit", "deployed_at"}
    assert body["status"] == "ok" and body["server"] == "looki-mcp"
    assert body["version"] == server.__version__
    assert body["tools"] >= 1
    assert body["commit"] == "unknown" and body["deployed_at"] == "unknown"


def test_version_matches_pyproject():
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert f'version = "{server.__version__}"' in text


def test_commit_from_deployed_sha():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".deployed-sha"
        p.write_text("abc1234\n")
        server.DEPLOYED_SHA_PATH = p
        os.environ.pop("LOOKI_MCP_COMMIT", None)
        body = _get()
        assert body["commit"] == "abc1234"
        assert body["deployed_at"].endswith("Z") and body["deployed_at"] != "unknown"


def test_env_overrides_commit():
    server.DEPLOYED_SHA_PATH = Path("/nonexistent/.deployed-sha")
    os.environ["LOOKI_MCP_COMMIT"] = "envsha"
    try:
        assert _get()["commit"] == "envsha"
    finally:
        os.environ.pop("LOOKI_MCP_COMMIT", None)


def main():
    test_payload_keys_and_version(); test_version_matches_pyproject()
    test_commit_from_deployed_sha(); test_env_overrides_commit()
    print("\033[32mPASS\033[0m /health endpoint")


if __name__ == "__main__":
    main()
