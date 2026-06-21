"""Unit tests for the pure MinIO/storage helpers (no network, no boto3 calls).

Run: .venv/bin/python scripts/test_storage_helpers.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp import storage  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok: {msg}")


def main() -> int:
    url = "https://user.file.devo.looki.ai/u/processed/dietary_image/1782003809432.jpg?x-looki-token=SECRET"

    print("media_key determinism + scheme")
    k1 = storage.media_key("jid-1", "2026-06-18", 0, "source", url)
    k2 = storage.media_key("jid-1", "2026-06-18", 0, "source", url)
    check(k1 == k2, "same inputs -> identical key (idempotent)")
    check(k1 == "journals/2026-06-18/jid-1/0_source.jpg", f"key scheme matches expectation (got {k1})")
    check(storage.media_key("jid-1", "2026-06-18", 1, "thumb", url).endswith("1_thumb.jpg"),
          "thumb kind + index reflected in key")
    check("SECRET" not in k1 and "x-looki-token" not in k1, "key never embeds the JWT query string")
    check(storage.media_key("j", None, 0, "source", url).startswith("journals/undated/"),
          "missing date -> 'undated' partition")

    print("extension inference")
    check(storage._ext_from_url("https://h/a/b.png?token=x") == ".png", "infers .png")
    check(storage._ext_from_url("https://h/a/b?token=x") == ".jpg", "no extension -> default .jpg")

    print("content type")
    check(storage._content_type_for("x/y/0_source.jpg", None) == "image/jpeg", "jpg -> image/jpeg")
    check(storage._content_type_for("x/y/0_source.weird", "image/png") == "image/png",
          "unknown ext falls back to provided content-type")
    check(storage._content_type_for("x/y/0_source.weird", None) == "application/octet-stream",
          "unknown ext + no fallback -> octet-stream")

    print("ascii-safe metadata")
    check(storage._ascii_safe("café \U0001f600") .isascii(), "non-ascii coerced to ascii")
    check(storage._ascii_safe(None) == "", "None -> empty string")

    print("env gating (configured / bucket)")
    saved = {k: os.environ.get(k) for k in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        check(storage.minio_configured() is False, "no env -> not configured")
        check(storage.get_bucket() == "looki-journal-media", "default bucket when unset")
        os.environ["MINIO_ENDPOINT"] = "http://x:9000"
        os.environ["MINIO_ACCESS_KEY"] = "ak"
        os.environ["MINIO_SECRET_KEY"] = "sk"
        os.environ["MINIO_BUCKET"] = "custom-bucket"
        check(storage.minio_configured() is True, "endpoint + both keys -> configured")
        check(storage.get_bucket() == "custom-bucket", "honors MINIO_BUCKET override")
        os.environ.pop("MINIO_ACCESS_KEY")
        check(storage.minio_configured() is False, "missing one credential -> not configured")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print()
    if failures:
        print(f"FAILED ({len(failures)})")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
