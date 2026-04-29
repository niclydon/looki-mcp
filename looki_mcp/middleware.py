"""Custom ASGI middleware for looki-mcp.

OriginSecretMiddleware: enforces a shared-secret header on every request
except `/health` and `/logo.ico` (which need to remain reachable for
monitoring and icon display without sharing the secret).
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


# Paths that bypass the origin-secret check. Keep this small and well-justified:
# /health is needed for Docker / load-balancer health checks; /logo.ico is read
# by MCP clients (claude.ai, etc.) to display the server's icon — those reads
# happen before any session is established, so they can't carry the secret.
EXEMPT_PATHS = frozenset({"/health", "/logo.ico"})


class OriginSecretMiddleware(BaseHTTPMiddleware):
    """Rejects requests that don't carry the configured `x-origin-secret` header.

    Returns 401 Unauthorized on mismatch (no body leak — just the JSON {"error": "unauthorized"}).
    Uses constant-time string comparison to avoid timing side-channels.
    """

    def __init__(self, app: ASGIApp, secret: str) -> None:
        super().__init__(app)
        if not secret:
            raise ValueError("OriginSecretMiddleware requires a non-empty secret")
        self._secret = secret

    async def dispatch(
        self,
        request: Request,
        call_next,  # type: ignore[no-untyped-def]
    ) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        provided = request.headers.get("x-origin-secret", "")
        if not hmac.compare_digest(provided, self._secret):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return await call_next(request)
