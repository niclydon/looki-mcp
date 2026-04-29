"""Download the Looki favicon and save as assets/looki-logo.ico.

Run: .venv/bin/python scripts/download_logo.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

LOGO_URL = "https://web.looki.ai/favicon.ico"
DEST = Path(__file__).parent.parent / "assets" / "looki-logo.ico"


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {LOGO_URL} -> {DEST}")
    try:
        urllib.request.urlretrieve(LOGO_URL, DEST)
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    size = DEST.stat().st_size
    print(f"OK: {size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
