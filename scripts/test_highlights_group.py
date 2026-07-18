"""Unit tests for get_highlights group validation (live API enum).

Run: .venv/bin/python scripts/test_highlights_group.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools.highlights import (  # noqa: E402
    VALID_GROUPS,
    validate_highlights_group,
)


def test_valid_groups_match_live_api():
    assert VALID_GROUPS == frozenset({"all", "vlog", "other"})
    assert "comic" not in VALID_GROUPS
    assert "present" not in VALID_GROUPS


def test_validate_accepts_live_values():
    for g in ("all", "vlog", "other"):
        assert validate_highlights_group(g) is None, g


def test_validate_rejects_comic_and_present():
    for g in ("comic", "present", "COMIC", "vlogs"):
        err = validate_highlights_group(g)
        assert err is not None and err.startswith("Error:"), (g, err)
        assert "comic" not in err or g == "comic"  # message lists sorted allowed only
        assert "all" in err and "vlog" in err and "other" in err


def main():
    test_valid_groups_match_live_api()
    test_validate_accepts_live_values()
    test_validate_rejects_comic_and_present()
    print("\033[32mPASS\033[0m highlights_group")


if __name__ == "__main__":
    main()
