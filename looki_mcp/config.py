"""Config loading, validation, and Looki base URL verification.

Loads credentials from environment variables (or a .env file via python-dotenv),
validates their format, and verifies the base URL with the Looki verification
endpoint before the server starts accepting connections.
"""

from __future__ import annotations

import os
import sys
import zoneinfo
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from the project root (one level above the looki_mcp package),
# so the server works whether started from the project dir or a subdir.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass
class Config:
    base_url: str
    api_key: str
    port: int
    bind_host: str
    public_url: str | None
    origin_shared_secret: str | None
    user_timezone: str | None
    tls_cert_path: str | None
    tls_key_path: str | None

    @property
    def tls_enabled(self) -> bool:
        return self.tls_cert_path is not None and self.tls_key_path is not None

    @property
    def scheme(self) -> str:
        return "https" if self.tls_enabled else "http"


_config: Config | None = None


async def load_and_validate_config() -> Config:
    """Load env vars, validate format, and verify base_url with Looki.

    Exits with a clear error message and code 1 if any check fails.
    """
    global _config

    base_url = os.getenv("LOOKI_BASE_URL", "").strip()
    api_key = os.getenv("LOOKI_API_KEY", "").strip()
    port_str = os.getenv("LOOKI_PORT", "3456")
    bind_host = os.getenv("LOOKI_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0"
    public_url = os.getenv("LOOKI_MCP_BASE_URL", "").strip() or None
    origin_shared_secret = os.getenv("ORIGIN_SHARED_SECRET", "").strip() or None
    user_timezone = os.getenv("LOOKI_USER_TIMEZONE", "").strip() or None
    tls_cert_path = os.getenv("LOOKI_TLS_CERT_PATH", "").strip() or None
    tls_key_path = os.getenv("LOOKI_TLS_KEY_PATH", "").strip() or None

    missing: list[str] = []
    if not base_url:
        missing.append("LOOKI_BASE_URL")
    if not api_key:
        missing.append("LOOKI_API_KEY")

    if missing:
        print(f"\nlooki-mcp: Missing required environment variables: {', '.join(missing)}\n", file=sys.stderr)
        print("Setup:", file=sys.stderr)
        print("  1. Copy .env.example to .env", file=sys.stderr)
        print("  2. Generate your base URL and API key at https://web.looki.ai/api-keys", file=sys.stderr)
        print("  3. Paste them into .env as LOOKI_BASE_URL and LOOKI_API_KEY", file=sys.stderr)
        print("  4. Run: python main.py\n", file=sys.stderr)
        sys.exit(1)

    if not api_key.startswith("lk-"):
        print("looki-mcp: LOOKI_API_KEY must start with 'lk-'", file=sys.stderr)
        print("  Generate your API key at https://web.looki.ai/api-keys", file=sys.stderr)
        sys.exit(1)

    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        print(f"looki-mcp: Invalid LOOKI_PORT '{port_str}'. Must be a number 1-65535.", file=sys.stderr)
        sys.exit(1)

    if user_timezone:
        try:
            zoneinfo.ZoneInfo(user_timezone)
        except Exception:
            print(
                f"looki-mcp: Invalid LOOKI_USER_TIMEZONE '{user_timezone}'.",
                file=sys.stderr,
            )
            print(
                "  Use an IANA name like 'America/New_York', 'Europe/London', or 'UTC'.",
                file=sys.stderr,
            )
            print(
                "  See: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
                file=sys.stderr,
            )
            sys.exit(1)

    # TLS: both cert and key must be set together, and both files must exist
    if (tls_cert_path is None) != (tls_key_path is None):
        which_set = "LOOKI_TLS_CERT_PATH" if tls_cert_path else "LOOKI_TLS_KEY_PATH"
        which_missing = "LOOKI_TLS_KEY_PATH" if tls_cert_path else "LOOKI_TLS_CERT_PATH"
        print(
            f"looki-mcp: {which_set} is set but {which_missing} is not.",
            file=sys.stderr,
        )
        print("  TLS requires both a certificate AND a private key. Set both, or unset both.", file=sys.stderr)
        sys.exit(1)
    if tls_cert_path and not Path(tls_cert_path).is_file():
        print(f"looki-mcp: LOOKI_TLS_CERT_PATH '{tls_cert_path}' does not exist or is not a file.", file=sys.stderr)
        sys.exit(1)
    if tls_key_path and not Path(tls_key_path).is_file():
        print(f"looki-mcp: LOOKI_TLS_KEY_PATH '{tls_key_path}' does not exist or is not a file.", file=sys.stderr)
        sys.exit(1)

    print("looki-mcp: Verifying Looki base URL...", flush=True)
    verify_url = f"https://open.looki.ai/api/v1/verify?endpoint={base_url}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(verify_url)
            response.raise_for_status()
            data = response.json()
            # Success response: {"status": "ok"}
            if data.get("status") != "ok":
                detail = data.get("detail") or data.get("message") or "endpoint not accepted"
                print(f"looki-mcp: Base URL verification failed: {detail}", file=sys.stderr)
                print("  Check that LOOKI_BASE_URL matches exactly what the Looki app shows.", file=sys.stderr)
                sys.exit(1)
    except httpx.HTTPStatusError as exc:
        # Failure responses look like: 403 {"code":104,"detail":"domain not allowed",...}
        try:
            err_body = exc.response.json()
            detail = err_body.get("detail") or err_body.get("message") or "rejected"
        except Exception:
            detail = exc.response.text[:120] or "rejected"
        print(f"looki-mcp: Base URL rejected by Looki (HTTP {exc.response.status_code}): {detail}", file=sys.stderr)
        print("  Check your LOOKI_BASE_URL value.", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as exc:
        print(f"looki-mcp: Could not reach Looki verification endpoint: {exc}", file=sys.stderr)
        print("  Check your internet connection and try again.", file=sys.stderr)
        sys.exit(1)

    print("looki-mcp: Base URL verified OK.", flush=True)
    _config = Config(
        base_url=base_url,
        api_key=api_key,
        port=port,
        bind_host=bind_host,
        public_url=public_url,
        origin_shared_secret=origin_shared_secret,
        user_timezone=user_timezone,
        tls_cert_path=tls_cert_path,
        tls_key_path=tls_key_path,
    )
    return _config


def get_config() -> Config:
    """Returns the loaded config. Raises if load_and_validate_config wasn't called first."""
    if _config is None:
        raise RuntimeError(
            "Config not initialized — call load_and_validate_config() before starting the server"
        )
    return _config
