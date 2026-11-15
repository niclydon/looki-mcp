"""Unit tests for the search_journals multi-term locator (no server, no .env).

Covers OB-69876: multi-term queries must match entries containing ALL terms in
any order across title/description/content, instead of requiring the exact
phrase as one contiguous substring. Single-term behavior is unchanged (same
entry set and same matched_field priority as the old exact-phrase scan).

Run: .venv/bin/python scripts/test_journals_search.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.tools.journals import (  # noqa: E402
    _entry_search_match,
    _search_terms,
    _shape_entry,
)


def _entry(eid, etype="AUDIO_SUMMARY", *, title=None, description=None, content=None):
    return {
        "id": eid,
        "type": etype,
        "title": title,
        "description": description,
        "content": content,
        "date": "2026-11-09",
    }


# The OB-69876 reproduction entry: all four terms appear in one AUDIO_SUMMARY
# entry ("Open Enrollment and Benefits Discussion") but never contiguously, so
# the old exact-phrase scan returned 0 matches while "saunas" alone hit.
REPRO_ENTRY = _entry(
    "enroll-1",
    title="Open Enrollment and Benefits Discussion",
    description="HR benefits talk",
    content="We discussed saunas and guided massage, plus FSA-eligible devices in the wellness room.",
)

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok: {msg}")


def main() -> int:
    print("test _search_terms")
    check(_search_terms("saunas massage devices FSA") == ["saunas", "massage", "devices", "fsa"],
          "multi-term query splits on whitespace, lowercased")
    check(_search_terms("saunas") == ["saunas"], "single term unchanged")
    check(_search_terms("  Tabletop   DEBRIEF  insider ") == ["tabletop", "debrief", "insider"],
          "extra whitespace collapses, case folded")
    check(_search_terms("   ") == ["   "], "whitespace-only falls back to raw needle (no all([]) match-all)")

    print("test multi-term reproduction (OB-69876)")
    matched, field, _term = _entry_search_match(REPRO_ENTRY, _search_terms("saunas massage devices FSA"))
    check(matched and field == "content", "4-term scattered query matches the Open Enrollment entry")
    single_matched, single_field, _ = _entry_search_match(REPRO_ENTRY, _search_terms("saunas"))
    check(single_matched and single_field == "content", "single-term query still hits the same entry")

    print("test any-order + exact-phrase preservation")
    entry2 = _entry("t1", title="Insider threat tabletop debrief", content="debrief notes about the tabletop exercise")
    check(_entry_search_match(entry2, _search_terms("insider threat tabletop"))[0],
          "phrase-order query matches")
    check(_entry_search_match(entry2, _search_terms("tabletop debrief insider"))[0],
          "reverse-order query matches (was 0 before the fix)")
    exact = _entry("e1", content="the insider threat tabletop ran for an hour")
    check(_entry_search_match(exact, _search_terms("insider threat tabletop"))[0],
          "exact contiguous phrase still matches")

    print("test all-terms-required semantics")
    missing_one = _entry("m1", content="saunas and massage only")
    check(not _entry_search_match(missing_one, _search_terms("saunas massage devices"))[0],
          "missing one term -> no match (AND, not OR/partial ranking)")
    partial_other = _entry("m2", title="saunas", content="nothing relevant here")
    check(not _entry_search_match(partial_other, _search_terms("saunas devices"))[0],
          "one term only -> no match")

    print("test cross-field match")
    cross = _entry("c1", title="Saunas overview", description="wellness devices", content="massage and FSA details inside")
    matched, field, _ = _entry_search_match(cross, _search_terms("saunas massage devices fsa"))
    check(matched, "terms spread across title/description/content still match")
    check(field in {"title", "description", "content"}, "cross-field pick returns a real field")

    print("test matched_field priority (single-term == old scan)")
    both = _entry("b1", title="saunas in title", description="saunas in desc", content="saunas in content")
    check(_entry_search_match(both, _search_terms("saunas"))[1] == "title",
          "single-term picks first field in title->description->content order")
    richest = _entry("r1", title="saunas", description="nope", content="saunas massage devices fsa all together")
    check(_entry_search_match(richest, _search_terms("saunas massage devices fsa"))[1] == "content",
          "multi-term picks the field with most hits")
    tie = _entry("t2", title="saunas massage", description="devices fsa", content="unrelated")
    check(_entry_search_match(tie, _search_terms("saunas devices"))[1] == "title",
          "tie keeps the earlier field")

    print("test content returned in full (never truncated)")
    shaped = _shape_entry(REPRO_ENTRY, "summary")
    check(shaped.get("content") == REPRO_ENTRY["content"] and shaped.get("content_truncated") is False,
          "summary keeps full content, content_truncated=False")

    print("test non-string fields tolerated")
    weird = {"id": "w", "title": None, "description": 42, "content": "saunas"}
    matches, _, _ = _entry_search_match(weird, _search_terms("saunas"))
    check(matches, "non-string title/description ignored, content still searched")
    check(not _entry_search_match({"id": "n"}, _search_terms("saunas"))[0],
          "entry with no searchable text -> no match")

    print()
    if failures:
        print(f"FAILED ({len(failures)})")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
