"""MinIO/S3 capture for journal media (optional feature).

Journal media `temporary_url`s are short-lived (~10 min) JWTs, so the only way to
keep the AI-generated images is to copy the bytes into durable object storage
while the URL is still valid. This module does that against a MinIO/S3 endpoint.

Configured entirely via env vars — when they're unset, capture is a graceful
no-op (mirrors the Forge / Langfuse / ffmpeg optional-feature pattern elsewhere
in this server). Reads `os.environ` directly rather than the startup Config so
the feature stays self-contained:

    MINIO_ENDPOINT      e.g. http://crucible.niclydon.io:9000   (required to enable)
    MINIO_ACCESS_KEY                                            (required to enable)
    MINIO_SECRET_KEY                                            (required to enable)
    MINIO_BUCKET        default "looki-journal-media"

boto3 is synchronous, so every blocking S3 call is offloaded with
`asyncio.to_thread` to avoid stalling the MCP server's event loop.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx

_DEFAULT_BUCKET = "looki-journal-media"

# Hard ceiling on a single media download. Journal media is AI-generated images
# (~1–2 MB observed), so 50 MB is generous while preventing a pathologically
# large (or redirect-swapped) body from OOMing this long-lived server process —
# capture runs transparently on get_journal_entry reads, so the cap matters.
_MAX_MEDIA_BYTES = 50 * 1024 * 1024

# Cached singletons for the life of the process. `_client` uses a `False`
# sentinel to distinguish "not yet built" from "built but unavailable (None)".
_client: Any | None | bool = False
_bucket_ensured = False

_EXT_RE = re.compile(r"\.([a-zA-Z0-9]{1,5})$")
_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
}


def minio_configured() -> bool:
    """True when endpoint + both credentials are present in the environment."""
    return bool(
        os.environ.get("MINIO_ENDPOINT", "").strip()
        and os.environ.get("MINIO_ACCESS_KEY", "").strip()
        and os.environ.get("MINIO_SECRET_KEY", "").strip()
    )


def get_bucket() -> str:
    return os.environ.get("MINIO_BUCKET", "").strip() or _DEFAULT_BUCKET


def _ext_from_url(url: str, default: str = ".jpg") -> str:
    path = url.split("?", 1)[0]
    match = _EXT_RE.search(path)
    return ("." + match.group(1).lower()) if match else default


def media_key(journal_id: str, date: str | None, idx: int, kind: str, url: str) -> str:
    """Deterministic, idempotent object key for one media file.

    Date-partitioned and entry-scoped so re-capturing the same media overwrites
    the same key (never duplicates): journals/<date>/<journal_id>/<idx>_<kind><ext>.
    `kind` is "source" or "thumb".
    """
    safe_date = date or "undated"
    return f"journals/{safe_date}/{journal_id}/{idx}_{kind}{_ext_from_url(url)}"


def _content_type_for(key: str, fallback: str | None) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return _CONTENT_TYPES.get(ext) or (fallback or "application/octet-stream")


def _ascii_safe(value: Any) -> str:
    """S3/MinIO object metadata must be ASCII. Coerce + truncate defensively."""
    return str(value or "").encode("ascii", "replace").decode("ascii")[:1024]


def get_client() -> Any | None:
    """Returns a cached boto3 S3 client, or None when MinIO is not configured."""
    global _client
    if not minio_configured():
        return None
    if _client is False:
        try:
            import boto3
            from botocore.config import Config

            _client = boto3.client(
                "s3",
                endpoint_url=os.environ["MINIO_ENDPOINT"].strip(),
                aws_access_key_id=os.environ["MINIO_ACCESS_KEY"].strip(),
                aws_secret_access_key=os.environ["MINIO_SECRET_KEY"].strip(),
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            )
        except Exception:
            _client = None
    return _client


async def ensure_bucket(client: Any) -> None:
    """Creates the target bucket if missing (cached after first success)."""
    global _bucket_ensured
    if _bucket_ensured:
        return
    bucket = get_bucket()

    def _ensure() -> None:
        try:
            client.head_bucket(Bucket=bucket)
        except Exception:
            client.create_bucket(Bucket=bucket)

    await asyncio.to_thread(_ensure)
    _bucket_ensured = True


async def object_exists(client: Any, key: str) -> bool:
    bucket = get_bucket()

    def _head() -> bool:
        try:
            client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    return await asyncio.to_thread(_head)


async def capture_url(
    client: Any,
    url: str,
    key: str,
    metadata: dict | None = None,
    *,
    overwrite: bool = False,
    timeout: float = 30.0,
) -> dict:
    """Downloads `url` and stores it at `key`. Idempotent and never raises.

    Returns a report dict with `status` one of: already_captured | captured |
    failed. The temporary_url needs no auth (the JWT is in the query string).
    """
    bucket = get_bucket()
    if not overwrite and await object_exists(client, key):
        return {"key": key, "bucket": bucket, "status": "already_captured"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            async with http.stream("GET", url) as resp:
                resp.raise_for_status()
                # Reject up front when the server declares an oversized body...
                declared = int(resp.headers.get("content-length") or 0)
                if declared > _MAX_MEDIA_BYTES:
                    return {
                        "key": key,
                        "bucket": bucket,
                        "status": "failed",
                        "error": f"media too large: {declared} bytes exceeds {_MAX_MEDIA_BYTES} cap",
                    }
                content_type = _content_type_for(key, resp.headers.get("content-type"))
                # ...and enforce the cap while streaming, in case Content-Length
                # was absent or understated.
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > _MAX_MEDIA_BYTES:
                        return {
                            "key": key,
                            "bucket": bucket,
                            "status": "failed",
                            "error": f"media exceeded {_MAX_MEDIA_BYTES} byte cap mid-stream",
                        }
                data = bytes(buf)
        meta = {_ascii_safe(k): _ascii_safe(v) for k, v in (metadata or {}).items()}

        def _put() -> None:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=meta,
            )

        await asyncio.to_thread(_put)
        return {
            "key": key,
            "bucket": bucket,
            "status": "captured",
            "size": len(data),
            "content_type": content_type,
        }
    except Exception as exc:
        return {"key": key, "bucket": bucket, "status": "failed", "error": str(exc)[:200]}
