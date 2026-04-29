"""Config loading, validation, and Looki base URL verification.

Loads credentials from environment variables (or a .env file via python-dotenv),
validates their format, and verifies the base URL with the Looki verification
endpoint before the server starts accepting connections.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    base_url: str
    api_key: str
    port: int
    public_url: str | None
    origin_shared_secret: str | None


_config: Config | None = None


async def load_and_validate_config() -> Config:
    """Load env vars, validate format, and verify base_url with Looki.

    Exits with a clear error message and code 1 if any check fails.
    """
    global _config

    base_url = os.getenv("LOOKI_BASE_URL", "").strip()
    api_key = os.getenv("LOOKI_API_KEY", "").strip()
    port_str = os.getenv("LOOKI_PORT", "3456")
    public_url = os.getenv("LOOKI_MCP_BASE_URL", "").strip() or None
    origin_shared_secret = os.getenv("ORIGIN_SHARED_SECRET", "").strip() or None

    missing: list[str] = []
    if not base_url:
        missing.append("LOOKI_BASE_URL")
    if not api_key:
        missing.append("LOOKI_API_KEY")

    if missing:
        print(f"\nlooki-mcp: Missing required environment variables: {', '.join(missing)}\n", file=sys.stderr)
        print("Setup:", file=sys.stderr)
        print("  1. Copy .env.example to .env", file=sys.stderr)
        print("  2. LOOKI_BASE_URL — find this in the Looki app -> Settings -> Developer", file=sys.stderr)
        print("  3. LOOKI_API_KEY  — your API key (starts with lk-)", file=sys.stderr)
        print("  4. Run: python main.py\n", file=sys.stderr)
        sys.exit(1)

    if not api_key.startswith("lk-"):
        print("looki-mcp: LOOKI_API_KEY must start with 'lk-'", file=sys.stderr)
        print("  Check the Looki app -> Settings -> Developer for your API key.", file=sys.stderr)
        sys.exit(1)

    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        print(f"looki-mcp: Invalid LOOKI_PORT '{port_str}'. Must be a number 1-65535.", file=sys.stderr)
        sys.exit(1)

    print("looki-mcp: Verifying Looki base URL...")
    verify_url = f"https://open.looki.ai/api/v1/verify?endpoint={base_url}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(verify_url)
            response.raise_for_status()
            data = response.json()
            if not data.get("valid"):
                msg = data.get("message", "Invalid endpoint")
                print(f"looki-mcp: Base URL verification failed: {msg}", file=sys.stderr)
                print("  Check that LOOKI_BASE_URL matches exactly what the Looki app shows.", file=sys.stderr)
                sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print(f"looki-mcp: Base URL rejected by Looki (HTTP {exc.response.status_code}).", file=sys.stderr)
        print("  Check your LOOKI_BASE_URL value.", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as exc:
        print(f"looki-mcp: Could not reach Looki verification endpoint: {exc}", file=sys.stderr)
        print("  Check your internet connection and try again.", file=sys.stderr)
        sys.exit(1)

    print("looki-mcp: Base URL verified OK.")
    _config = Config(
        base_url=base_url,
        api_key=api_key,
        port=port,
        public_url=public_url,
        origin_shared_secret=origin_shared_secret,
    )
    return _config


def get_config() -> Config:
    """Returns the loaded config. Raises if load_and_validate_config wasn't called first."""
    if _config is None:
        raise RuntimeError(
            "Config not initialized — call load_and_validate_config() before starting the server"
        )
    return _config
