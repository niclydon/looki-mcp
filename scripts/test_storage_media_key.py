"""Tests for storage.media_key_for. Run: .venv/bin/python scripts/test_storage_media_key.py"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.storage import media_key_for, media_key  # noqa: E402

def test_moment_namespace():
    k = media_key_for("moments", "M123", "2026-06-20", 0, "hero", "http://x/p.png?t=1")
    assert k == "moments/2026-06-20/M123/0_hero.png", k

def test_undated_and_default_ext():
    k = media_key_for("insight", "Y1", None, 2, "source", "http://x/noext")
    assert k == "insight/undated/Y1/2_source.jpg", k

def test_journal_key_unchanged():
    assert media_key("J1", "2026-06-20", 0, "source", "http://x/a.jpg").startswith("journals/2026-06-20/J1/")

def main():
    test_moment_namespace(); test_undated_and_default_ext(); test_journal_key_unchanged()
    print("\033[32mPASS\033[0m storage.media_key_for")

if __name__ == "__main__":
    main()
