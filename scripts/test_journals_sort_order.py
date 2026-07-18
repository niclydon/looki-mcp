"""Unit tests for journals sort_order wire normalization.

Run: .venv/bin/python scripts/test_journals_sort_order.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools.journals import normalize_sort_order  # noqa: E402


def test_lowercase_wire_values():
    assert normalize_sort_order("asc") == "asc"
    assert normalize_sort_order("desc") == "desc"


def test_uppercase_aliases():
    assert normalize_sort_order("ASC") == "asc"
    assert normalize_sort_order("DESC") == "desc"


def test_mixed_and_whitespace():
    assert normalize_sort_order(" Asc ") == "asc"
    assert normalize_sort_order("DeSc") == "desc"


def test_invalid_rejected():
    assert normalize_sort_order("up") is None
    assert normalize_sort_order("") is None
    assert normalize_sort_order("ascending") is None


def test_default_desc_omitted_from_params_logic():
    """When wire is desc, get_journals omits sort_order (API default)."""
    wire = normalize_sort_order("DESC")
    assert wire == "desc"
    params: dict[str, str | int] = {"max_days": 7}
    if wire != "desc":
        params["sort_order"] = wire
    assert "sort_order" not in params


def test_asc_is_sent_lowercase():
    wire = normalize_sort_order("ASC")
    assert wire == "asc"
    params: dict[str, str | int] = {"max_days": 7}
    if wire != "desc":
        params["sort_order"] = wire
    assert params["sort_order"] == "asc"


def main():
    test_lowercase_wire_values()
    test_uppercase_aliases()
    test_mixed_and_whitespace()
    test_invalid_rejected()
    test_default_desc_omitted_from_params_logic()
    test_asc_is_sent_lowercase()
    print("\033[32mPASS\033[0m journals_sort_order")


if __name__ == "__main__":
    main()
