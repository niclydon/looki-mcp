"""Entry point: validate config, then run the FastMCP HTTP server."""

from __future__ import annotations

import asyncio

from starlette.middleware import Middleware

from looki_mcp.config import Config, load_and_validate_config
from looki_mcp.middleware import OriginSecretMiddleware
from looki_mcp.server import TOOL_COUNT, mcp


async def _startup() -> Config:
    return await load_and_validate_config()


def run() -> None:
    config = asyncio.run(_startup())
    scheme = config.scheme
    print(
        f"[looki-mcp] Server running on {scheme}://0.0.0.0:{config.port}/mcp ({TOOL_COUNT} tools)",
        flush=True,
    )
    if config.tls_enabled:
        print(f"[looki-mcp] TLS enabled (cert: {config.tls_cert_path})", flush=True)
    else:
        print(
            "[looki-mcp] TLS disabled — for public exposure, terminate TLS at a reverse proxy "
            "(Cloudflare Tunnel, Caddy, nginx) or set LOOKI_TLS_CERT_PATH and LOOKI_TLS_KEY_PATH",
            flush=True,
        )
    if config.origin_shared_secret:
        print(
            "[looki-mcp] Origin-secret guard ENABLED "
            "(clients must send 'x-origin-secret' header)",
            flush=True,
        )
    else:
        print(
            "[looki-mcp] Origin-secret guard DISABLED — anyone who reaches the URL can call tools. "
            "Set ORIGIN_SHARED_SECRET for public deployments.",
            flush=True,
        )
    if config.public_url:
        print(f"[looki-mcp] Public MCP URL: {config.public_url}/mcp", flush=True)
        print(f"[looki-mcp] Icon URL:       {config.public_url}/logo.ico", flush=True)
    else:
        print("[looki-mcp] Tip: Set LOOKI_MCP_BASE_URL to enable icon display in MCP clients", flush=True)

    # show_banner=False suppresses FastMCP's promotional banner.
    # uvicorn_config forwards SSL paths to the underlying uvicorn server when TLS is enabled.
    uvicorn_config: dict[str, str] = {}
    if config.tls_enabled:
        # Both fields are guaranteed non-None here (tls_enabled checks both).
        assert config.tls_cert_path is not None
        assert config.tls_key_path is not None
        uvicorn_config["ssl_certfile"] = config.tls_cert_path
        uvicorn_config["ssl_keyfile"] = config.tls_key_path

    # Build ASGI middleware stack. Currently just origin-secret enforcement when configured.
    middleware: list[Middleware] = []
    if config.origin_shared_secret:
        middleware.append(
            Middleware(OriginSecretMiddleware, secret=config.origin_shared_secret)
        )

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=config.port,
        show_banner=False,
        uvicorn_config=uvicorn_config,
        middleware=middleware,
    )


if __name__ == "__main__":
    run()
