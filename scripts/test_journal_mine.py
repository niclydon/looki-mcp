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

def test_no_heading_keeps_todo_lines_and_sets_bullets_aside():
    # OB-70149: bullets with no recognised section are narration, never items.
    entry = {"content": "Random notes.\n- buy milk\nTODO: ship the thing\nmore prose"}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is False, out
    assert out["items"] == ["ship the thing"], out
    assert out["fallback_lines"] == ["buy milk"], out
    assert out["candidate_lines"] == len(out["items"])

def test_empty_is_safe():
    empty = {"items": [], "parsed_section": False, "candidate_lines": 0, "fallback_lines": []}
    assert extract_todo_section({"content": "just prose, nothing actionable"}) == empty
    assert extract_todo_section({}) == empty

def test_uses_description_when_no_content():
    entry = {"content": None, "description": "Action Items\n- one\n- two"}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is True and out["items"] == ["one", "two"], out

def test_heading_skips_prose_preamble():
    entry = {"content": "Action Items\n(see notes)\n- actually do this\n- and this\n\nNext"}
    out = extract_todo_section(entry)
    assert out["parsed_section"] is True, out
    assert out["items"] == ["actually do this", "and this"], out

def test_bold_markdown_heading():
    out = extract_todo_section({"content": "**Action Items**\n- one\n- two"})
    assert out["parsed_section"] is True and out["items"] == ["one", "two"], out

# Current (2026-11) shapes, synthetic text. YESTERDAY_RECAP ends in a markdown
# "Suggestions for Today" section of numbered items.
CURRENT_RECAP = (
    "### Morning\nYou walked to the market and met a friend.\n- Bought bread\n- Long chat by the water\n\n"
    "### Evening\n- Dinner outside\n\n"
    "### Suggestions for Today\n1. Call the dentist about Thursday\n2. Pack the camera bag\n3. Reply to Sam about the trip"
)
# AUDIO_SUMMARY with an Action items section whose bullets are blank-separated.
AUDIO_WITH_ACTIONS = (
    "### Key Takeaways\n- The launch slips a week\n- Budget is fine\n\n"
    "### Action items\n\n- Send the revised deck\n\n\n- Book the review room\n\n"
    "### Views\n- The team prefers a later date"
)
# AUDIO_SUMMARY with no follow-up section at all.
AUDIO_NO_ACTIONS = "### Key Takeaways\n- Point one\n- Point two\n\n### Views\n- A view"

def test_current_recap_suggestions_for_today():
    out = extract_todo_section({"type": "YESTERDAY_RECAP", "content": CURRENT_RECAP})
    assert out["parsed_section"] is True, out
    assert out["items"] == ["Call the dentist about Thursday", "Pack the camera bag",
                            "Reply to Sam about the trip"], out
    assert out["fallback_lines"] == []

def test_audio_action_items_across_blank_lines():
    out = extract_todo_section({"type": "AUDIO_SUMMARY", "content": AUDIO_WITH_ACTIONS})
    assert out["parsed_section"] is True, out
    assert out["items"] == ["Send the revised deck", "Book the review room"], out

def test_audio_without_follow_up_section_yields_no_items():
    out = extract_todo_section({"type": "AUDIO_SUMMARY", "content": AUDIO_NO_ACTIONS})
    assert out["parsed_section"] is False and out["items"] == [], out
    assert out["fallback_lines"] == ["Point one", "Point two", "A view"], out

def test_md_section_stops_at_next_heading_and_skips_prose():
    out = extract_todo_section({"content": "## Next steps\nSome prose first.\n- one\nmid prose\n- two\n## Other\n- not this"})
    assert out["items"] == ["one", "two"], out

def test_long_item_not_truncated():
    long = "Follow up with the contractor about " + "the kitchen estimate " * 40
    out = extract_todo_section({"content": "### Suggestions for Today\n1. " + long.strip()})
    assert out["items"] == [long.strip()]

def test_prose_starting_with_todo_is_not_a_commitment():
    # AR 83d1384b F1: TODO needs a colon.
    out = extract_todo_section({"content": "TODOs were discussed at length.\nTodo list app came up.\nTODO list review"})
    assert out["items"] == [] and out["parsed_section"] is False, out

def test_bullet_todo_line_is_a_commitment():
    out = extract_todo_section({"content": "### Key Takeaways\n- A point\n- TODO: call Ana\n- todo:   book the room"})
    assert out["items"] == ["call Ana", "book the room"], out
    assert out["fallback_lines"] == ["A point"], out

def test_plain_heading_inside_md_section_not_double_counted():
    # AR 83d1384b F2: single pass; a plain heading the markdown section already read is not re-read.
    out = extract_todo_section({"content": "### Action items\n- one\nNext steps\n- two\n### Views\n- v"})
    assert out["items"] == ["one", "two"], out

def test_two_distinct_sections_with_identical_items_both_count():
    out = extract_todo_section({"content": "### Action items\n- Send it\n### Views\n- v\n### Follow-ups\n- Send it"})
    assert out["items"] == ["Send it", "Send it"], out

def test_bullet_named_like_a_heading_is_not_a_section():
    # AR 83d1384b F3: "- Suggestions" is an item, never a heading.
    out = extract_todo_section({"type": "AUDIO_SUMMARY", "content": "### Key Takeaways\n- Suggestions\n- Point one\n- Point two"})
    assert out["parsed_section"] is False and out["items"] == [], out
    assert out["fallback_lines"] == ["Suggestions", "Point one", "Point two"], out

def main():
    test_heading_with_bullets()
    test_heading_variant_casing_and_punct()
    test_no_heading_keeps_todo_lines_and_sets_bullets_aside()
    test_empty_is_safe()
    test_uses_description_when_no_content()
    test_heading_skips_prose_preamble()
    test_bold_markdown_heading()
    test_current_recap_suggestions_for_today()
    test_audio_action_items_across_blank_lines()
    test_audio_without_follow_up_section_yields_no_items()
    test_md_section_stops_at_next_heading_and_skips_prose()
    test_long_item_not_truncated()
    test_prose_starting_with_todo_is_not_a_commitment()
    test_bullet_todo_line_is_a_commitment()
    test_plain_heading_inside_md_section_not_double_counted()
    test_two_distinct_sections_with_identical_items_both_count()
    test_bullet_named_like_a_heading_is_not_a_section()
    print("\033[32mPASS\033[0m journal_mine")

if __name__ == "__main__":
    main()
