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
or prose after the first item. The scan is single-pass, so a line is read by at
most one section, and a list item is never taken for a heading (``- Suggestions``
is an item, not a section).

A ``TODO`` line needs a colon (``TODO: call Ana``, also as a bullet), so prose
that merely starts with "TODOs" or "Todo list" is not a commitment.

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
_TODO_PREFIX_RE = re.compile(r"^\s*TODO\s*:\s*(.*\S)\s*$", re.IGNORECASE)
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


def _todo_text(line: str) -> str | None:
    """The text of a ``TODO:`` line, bare or as a list item, else None."""
    m = _TODO_PREFIX_RE.match(line)
    if m:
        return m.group(1).strip()
    m = _BULLET_RE.match(line)
    if m:
        m = _TODO_PREFIX_RE.match(m.group(1))
        if m:
            return m.group(1).strip()
    return None


def _is_heading(line: str) -> bool:
    """A recognised follow-up heading. A list item never counts, whatever it says."""
    if _BULLET_RE.match(line):
        return False
    return _clean_heading(line) in _TODO_HEADINGS


def _md_section(lines: list[str], start: int) -> tuple[list[str], int]:
    """Items under a markdown heading: every list line until the next markdown heading.

    Returns the items and the index where the section ends (the next markdown
    heading, or len(lines)); that line is not consumed.
    """
    items: list[str] = []
    i = start
    while i < len(lines):
        if _MD_HEADING_RE.match(lines[i]):
            break
        item = _as_item(lines[i])
        if item is not None:
            items.append(item)
        i += 1
    return items, i


def _plain_section(lines: list[str], start: int) -> tuple[list[str], int]:
    """Items under a plain-text heading: until a blank line or prose after the first item.

    Returns the items and the index of the line that ended the section, which is
    not consumed (it may be the next heading).
    """
    items: list[str] = []
    i = start
    while i < len(lines):
        follow = lines[i]
        if not follow.strip():
            if items:
                break
            i += 1
            continue
        item = _as_item(follow)
        if item is not None:
            items.append(item)
        elif items:
            break  # hit prose/next section after collecting items
        # else: non-item line before any item: skip prose preamble under the heading
        i += 1
    return items, i


def extract_todo_section(entry: dict) -> dict:
    text = entry.get("content") or entry.get("description") or ""
    lines = text.splitlines()

    # 1. Heading-anchored, single pass: each section resumes the scan where it
    #    ended, so no line is collected twice. Several sections in one entry count.
    items: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_heading(line):
            if _MD_HEADING_RE.match(line):
                found, i = _md_section(lines, i + 1)
            else:
                found, i = _plain_section(lines, i + 1)
            items.extend(found)
            continue
        i += 1
    if items:
        return {"items": items, "parsed_section": True, "candidate_lines": len(items),
                "fallback_lines": []}

    # 2. No recognised section: explicit TODO: lines are still follow-ups; every
    #    other list line is narration and goes to fallback_lines, never to items.
    todo_items: list[str] = []
    fallback: list[str] = []
    for ln in lines:
        todo = _todo_text(ln)
        if todo is not None:
            todo_items.append(todo)
            continue
        m = _BULLET_RE.match(ln)
        if m:
            fallback.append(m.group(1).strip())
    return {"items": todo_items, "parsed_section": False, "candidate_lines": len(todo_items),
            "fallback_lines": fallback}
