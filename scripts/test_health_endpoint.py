"""Tests for the /health payload. Run: .venv/bin/python scripts/test_health_endpoint.py"""
from __future__ import annotations
import os, sys, tempfile, tomllib
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOOKI_API_KEY", "test")
from starlette.testclient import TestClient  # noqa: E402
import looki_mcp.server as server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _get() -> dict:
    with TestClient(server.mcp.http_app()) as c:
        r = c.get("/health")
        assert r.status_code == 200
        return r.json()


@contextmanager
def _stamp(path: Path, env: str | None = None):
    """Point the server at `path` and set/clear LOOKI_MCP_COMMIT, restoring both."""
    old_path, old_env = server.DEPLOYED_SHA_PATH, os.environ.get("LOOKI_MCP_COMMIT")
    server.DEPLOYED_SHA_PATH = path
    if env is None:
        os.environ.pop("LOOKI_MCP_COMMIT", None)
    else:
        os.environ["LOOKI_MCP_COMMIT"] = env
    try:
        yield
    finally:
        server.DEPLOYED_SHA_PATH = old_path
        if old_env is None:
            os.environ.pop("LOOKI_MCP_COMMIT", None)
        else:
            os.environ["LOOKI_MCP_COMMIT"] = old_env


def test_payload_keys_and_version():
    with _stamp(Path("/nonexistent/.deployed-sha")):
        body = _get()
    assert set(body) == {"status", "server", "version", "tools", "git_commit", "deployed_at"}
    assert body["status"] == "ok" and body["server"] == "looki-mcp"
    assert body["version"] == server.__version__
    assert body["tools"] == server.TOOL_COUNT
    assert body["git_commit"] == "unknown" and body["deployed_at"] == "unknown"


def test_version_is_pyproject_with_no_literal():
    with open(ROOT / "pyproject.toml", "rb") as fh:
        assert server.__version__ == tomllib.load(fh)["project"]["version"]
    # The only source is pyproject.toml: no version literal remains in server.py.
    src = (ROOT / "looki_mcp" / "server.py").read_text()
    assert f'"{server.__version__}"' not in src, "version literal in server.py"


def test_commit_from_deployed_sha():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".deployed-sha"
        p.write_text("abc1234\n")
        with _stamp(p):
            body = _get()
    assert body["git_commit"] == "abc1234"
    assert body["deployed_at"].endswith("Z") and body["deployed_at"] != "unknown"


def test_stamp_is_fresh_across_rewrite_without_restart():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".deployed-sha"
        p.write_text("aaaaaaa\n")
        with _stamp(p):
            assert _get()["git_commit"] == "aaaaaaa"
            os.utime(p, (1_700_000_000, 1_700_000_000))
            p.write_text("bbbbbbb\n")
            os.utime(p, (1_800_000_000, 1_800_000_000))
            body = _get()
    assert body["git_commit"] == "bbbbbbb"
    assert body["deployed_at"] == "2027-01-15T08:00:00Z"


def test_empty_stamp_reports_both_unknown():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".deployed-sha"
        p.write_text("  \n")
        with _stamp(p):
            body = _get()
    assert body["git_commit"] == "unknown" and body["deployed_at"] == "unknown"


def test_env_commit_never_pairs_with_file_mtime():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".deployed-sha"
        p.write_text("filesha\n")
        with _stamp(p, env="envsha"):
            body = _get()
    assert body["git_commit"] == "envsha" and body["deployed_at"] == "unknown"
    assert "LOOKI_MCP_COMMIT" not in os.environ or os.environ["LOOKI_MCP_COMMIT"] != "envsha"


def main():
    test_payload_keys_and_version(); test_version_is_pyproject_with_no_literal()
    test_commit_from_deployed_sha(); test_stamp_is_fresh_across_rewrite_without_restart()
    test_empty_stamp_reports_both_unknown(); test_env_commit_never_pairs_with_file_mtime()
    print("\033[32mPASS\033[0m /health endpoint")


if __name__ == "__main__":
    main()
