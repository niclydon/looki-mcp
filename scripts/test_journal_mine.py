"""Unit tests for journal_mine.extract_todo_section (pure, no network).
Run: .venv/bin/python scripts/test_journal_mine.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.insight.journal_mine import extract_todo_section  # noqa: E402

def test_heading_with_bullets():
    entry = {"type": "YESTERDAY_RECAP", "content":
        "Recap\nYou had a good day.\n\nActionable Suggestions\n- Email Bob about Q2\n- Book the dentist\n\nDietary\nAte well."}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is True, out
    assert out["items"] == ["Email Bob about Q2", "Book the dentist"], out
    assert out["candidate_lines"] == 2

def test_heading_variant_casing_and_punct():
    entry = {"content": "## TODOs:\n1. Call mom\n2. Renew passport\nNext section\nblah"}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is True
    assert out["items"] == ["Call mom", "Renew passport"], out

def test_fallback_no_heading_scans_body():
    entry = {"content": "Random notes.\n- buy milk\nTODO: ship the thing\nmore prose"}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is False, out
    assert "buy milk" in out["items"] and "ship the thing" in out["items"], out
    assert out["candidate_lines"] == len(out["items"])

def test_empty_is_safe():
    assert extract_todo_section({"content": "just prose, nothing actionable"}) == {"items": [], "parsed_section": False, "candidate_lines": 0}
    assert extract_todo_section({}) == {"items": [], "parsed_section": False, "candidate_lines": 0}

def test_uses_description_when_no_content():
    entry = {"content": None, "description": "Action Items\n- one\n- two"}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is True and out["items"] == ["one", "two"], out

def main():
    test_heading_with_bullets()
    test_heading_variant_casing_and_punct()
    test_fallback_no_heading_scans_body()
    test_empty_is_safe()
    test_uses_description_when_no_content()
    print("\033[32mPASS\033[0m journal_mine")

if __name__ == "__main__":
    main()
