"""Best-effort extraction of follow-up items from AI journal text.

The Looki journal section headings are OBSERVED, not contractual (see
journals_api_findings.md). As of 2026-11-16 the shapes in use are:

- YESTERDAY_RECAP: a markdown ``### Suggestions for Today`` section of numbered
  items (older recaps used a plain ``Actionable Suggestions`` / ``TODOs`` line).
- AUDIO_SUMMARY / MANUAL_AUDIO_SUMMARY: ``### Key Takeaways`` and ``### Views``
  (narration), plus a ``### Action items`` section of dash bullets that is often
  absent and whose bullets are separated by one or more blank lines.

So extraction is tolerant: it matches a set of heading variants, and a markdown
(``#``) heading's section runs to the next markdown heading, skipping blank and
prose lines. A plain-text heading keeps the older rule: items until a blank line
or prose after the first item.

Only a recognised section, or an explicit ``TODO:`` line, yields ``items``. Other
list lines in an entry with no recognised section are narration, not follow-ups,
so they are returned separately as ``fallback_lines`` and never as items.
``parsed_section`` says whether a recognised section produced the items. Item
text is never truncated.
"""
from __future__ import annotations

import re

# Heading variants (compared case-insensitively after stripping markdown/punctuation).
_TODO_HEADINGS = {
    "actionable suggestions", "actionable", "todos", "to-dos", "to do",
    "action items", "actions", "todo", "next steps",
    "suggestions for today", "suggestions", "follow-ups", "follow ups",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)]|\[[ xX]?\])\s+(.*\S)\s*$")
_TODO_PREFIX_RE = re.compile(r"^\s*TODO\s*:?\s*(.*\S)\s*$", re.IGNORECASE)
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s")


def _clean_heading(line: str) -> str:
    """Lowercased heading text with markdown/punctuation stripped, for matching."""
    s = line.strip().lstrip("#*->").strip()
    s = s.rstrip(":).*_ ").strip()
    return s.lower()


def _as_item(line: str) -> str | None:
    """Returns the item text if `line` is a list item / TODO line, else None."""
    m = _BULLET_RE.match(line)
    if m:
        return m.group(1).strip()
    m = _TODO_PREFIX_RE.match(line)
    if m:
        return m.group(1).strip()
    return None


def _md_section_items(lines: list[str]) -> list[str]:
    """Items under a markdown heading: every list line until the next markdown heading."""
    items: list[str] = []
    for follow in lines:
        if _MD_HEADING_RE.match(follow):
            break
        item = _as_item(follow)
        if item is not None:
            items.append(item)
    return items


def _plain_section_items(lines: list[str]) -> list[str]:
    """Items under a plain-text heading: until a blank line or prose after the first item."""
    items: list[str] = []
    for follow in lines:
        if not follow.strip():
            if items:
                break
            continue
        item = _as_item(follow)
        if item is not None:
            items.append(item)
        elif items:
            break  # hit prose/next section after collecting items
        # else: non-item line before any item: skip prose preamble under the heading
    return items


def extract_todo_section(entry: dict) -> dict:
    text = entry.get("content") or entry.get("description") or ""
    lines = text.splitlines()

    # 1. Heading-anchored. Several recognised sections in one entry all count.
    items: list[str] = []
    for i, line in enumerate(lines):
        if _clean_heading(line) in _TODO_HEADINGS:
            if _MD_HEADING_RE.match(line):
                items.extend(_md_section_items(lines[i + 1:]))
            else:
                items.extend(_plain_section_items(lines[i + 1:]))
    if items:
        return {"items": items, "parsed_section": True, "candidate_lines": len(items),
                "fallback_lines": []}

    # 2. No recognised section: explicit TODO: lines are still follow-ups; every
    #    other list line is narration and goes to fallback_lines, never to items.
    todo_items: list[str] = []
    fallback: list[str] = []
    for ln in lines:
        m = _TODO_PREFIX_RE.match(ln)
        if m:
            todo_items.append(m.group(1).strip())
            continue
        m = _BULLET_RE.match(ln)
        if m:
            fallback.append(m.group(1).strip())
    return {"items": todo_items, "parsed_section": False, "candidate_lines": len(todo_items),
            "fallback_lines": fallback}
