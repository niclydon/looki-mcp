"""Single source of truth for looki-mcp version and deploy stamp (OB-69923).

Version resolution order:
1. Installed package metadata (importlib.metadata) — correct when the
   distribution is installed (e.g. pip install -e . or wheel).
2. pyproject.toml next to the package — the deployed service checkout is
   git-in-place and deploy.sh installs only requirements.txt, so no
   distribution metadata exists in the service venv. Reading pyproject
   keeps pyproject.toml as the single source of truth everywhere.
3. Fallback constant — only when both above are unavailable (dev tree
   without pyproject); never a release version.

git_commit / deployed_at come from .deployed-sha written by
scripts/deploy.sh at /services/looki-mcp/.deployed-sha. Read once at
import (startup); absent file (dev checkout) yields None.
Note deploy.sh writes .deployed-sha after the health check, so the first
deploy of a new sha reports the previous sha until the service restarts.
"""
from __future__ import annotations

import datetime
from importlib.metadata import PackageNotFoundError, version as _metadata_version
from pathlib import Path

_PACKAGE_NAME = "looki-mcp"
_FALLBACK = "0.0.0+unknown"
_REPO_ROOT = Path(__file__).parent.parent
_DEPLOYED_SHA_PATH = _REPO_ROOT / ".deployed-sha"
_PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"


def _version_from_metadata() -> str | None:
    try:
        return _metadata_version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return None


def _version_from_pyproject() -> str | None:
    try:
        import tomllib
    except ModuleNotFoundError:
        return None
    try:
        data = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) and version else None


def get_version() -> str:
    """Resolve the package version (metadata -> pyproject -> fallback)."""
    return _version_from_metadata() or _version_from_pyproject() or _FALLBACK


def _read_deployed_sha() -> str | None:
    try:
        sha = _DEPLOYED_SHA_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha or None


def _read_deployed_at() -> str | None:
    try:
        mtime = _DEPLOYED_SHA_PATH.stat().st_mtime
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()


__version__ = get_version()
GIT_COMMIT = _read_deployed_sha()
DEPLOYED_AT = _read_deployed_at()
