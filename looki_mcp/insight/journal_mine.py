"""Best-effort extraction from AI journal text.

The Looki journal section headings (e.g. YESTERDAY_RECAP's "Actionable
Suggestions"/"TODOs") are OBSERVED, not contractual (see journals_api_findings.md),
so extraction is tolerant: it matches a set of heading variants, and when none is
found it falls back to scanning the whole body for list/TODO lines — never a silent
empty. `parsed_section` tells the caller which path produced the result.
"""
from __future__ import annotations

import re

# Heading variants (compared case-insensitively after stripping markdown/punctuation).
_TODO_HEADINGS = {
    "actionable suggestions", "actionable", "todos", "to-dos", "to do",
    "action items", "actions", "todo", "next steps",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)]|\[[ xX]?\])\s+(.*\S)\s*$")
_TODO_PREFIX_RE = re.compile(r"^\s*TODO\s*:?\s*(.*\S)\s*$", re.IGNORECASE)


def _clean_heading(line: str) -> str:
    """Lowercased heading text with markdown/punctuation stripped, for matching."""
    s = line.strip().lstrip("#*->").strip()
    s = s.rstrip(":).").strip()
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


def extract_todo_section(entry: dict) -> dict:
    text = entry.get("content") or entry.get("description") or ""
    lines = text.splitlines()

    # 1. Heading-anchored: find a TODO heading, collect following list items until a
    #    blank line or the next heading-like (non-item, non-empty) line.
    for i, line in enumerate(lines):
        if _clean_heading(line) in _TODO_HEADINGS:
            items: list[str] = []
            for follow in lines[i + 1:]:
                if not follow.strip():
                    if items:
                        break
                    continue
                item = _as_item(follow)
                if item is not None:
                    items.append(item)
                elif items:
                    break  # hit prose/next section after collecting items
            if items:
                return {"items": items, "parsed_section": True, "candidate_lines": len(items)}

    # 2. Fallback: scan the whole body for list/TODO lines.
    items = [it for ln in lines if (it := _as_item(ln)) is not None]
    return {"items": items, "parsed_section": False, "candidate_lines": len(items)}
