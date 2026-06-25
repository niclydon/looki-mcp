# PR2 — LLM-Free Insight Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three LLM-free composite tools — `commitment_harvester`, `the_unwritten`, `places_of_my_life` — plus the two pure helper modules they need (`journal_mine`, `geo`), proving real value with **zero LLM/MinIO configuration**.

**Architecture:** Each tool separates **pure transform logic** (fully unit-testable with canned dicts, no network) from a thin **async `_gather_*`** that does the Looki I/O (via the PR1 governor/scanners) and a `@mcp.tool` wrapper that does `gather → transform → optional narrative → envelope`. Helper modules (`journal_mine`, `geo`) are pure and fixture-tested. This mirrors the repo's "pure helpers unit-tested off-network" convention.

**Tech Stack:** Python 3.11+, `fastmcp`, `httpx`. Builds on the merged PR1 Insight Core (`looki_mcp/insight/`: `governor`, `scan`, `cache`, `envelope`, `llm`). Tests are **standalone scripts** run with `.venv/bin/python scripts/test_*.py` (NO pytest).

## Global Constraints

- **Public repo, graceful degradation:** every tool returns useful structured JSON with **zero LLM config**. Optional `narrative` is computed via `insight.llm.synthesize` only when a provider is configured, else `null` — never raises.
- **Hybrid output contract:** every tool returns `insight.envelope.render(data, narrative=..., meta=...)` → `{data, narrative, meta}`. `meta` carries the uniform keys `{calls_used, days_scanned, capped, cache_hit, vlm_used, enrichment_skipped_reason}` (envelope fills defaults); truncation signals live in `meta`, never `data`.
- **Rate limit:** all multi-day Looki I/O goes through `insight.scan` walkers / `client.governed_get` (PR1 governor). Tools surface `calls_used` + `capped` in `meta`.
- **`location` is on `cover_file`, sometimes null, NOT a top-level moment field.** `places_of_my_life` defaults to `cover_file.location` (1 call/day); per-moment `/files` harvest is `deep=True` opt-in.
- **Journal headings are observed, not contractual** [spec B3]: `extract_todo_section` is tolerant (heading variants + bullet/`TODO:` fallback) and returns `parsed_section: false` + the full content's candidate-line count rather than a silent empty.
- **Timezone:** "recent"/"today"/window math reuses `convenience._today_local` / `_days_ago_local`.
- No new runtime dependencies. Tests deterministic — inject/patch data sources; never hit the network.
- **Deferred to PR3 (do NOT build here):** `journal_mine.extract_people`, `insight/temporal.py`, durable hero-image capture (`cache.capture_hero_image`), and the `[M5] enrichment_skipped_reason` population beyond the envelope default.

**Spec:** `docs/superpowers/specs/2026-06-24-looki-magic-composite-tools-design.md` (v2) — tools §4.2/§4.3/§4.9, helpers §3.3/§3.6.

**After this PR:** `TOOL_COUNT` 24 → **27**.

---

### Task 1: `insight/journal_mine.py` — tolerant TODO-section extraction

**Files:**
- Create: `looki_mcp/insight/journal_mine.py`
- Test: `scripts/test_journal_mine.py`

**Interfaces:**
- Produces: `def extract_todo_section(entry: dict) -> dict` → `{"items": list[str], "parsed_section": bool, "candidate_lines": int}`. Reads `entry["content"]` (falls back to `entry["description"]`). When a recognized TODO heading is found, returns the list items beneath it with `parsed_section=True`; otherwise falls back to scanning the whole body for bullet/`TODO:` lines with `parsed_section=False`; `candidate_lines` is `len(items)`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_journal_mine.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_journal_mine.py`
Expected: `ModuleNotFoundError: looki_mcp.insight.journal_mine`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/insight/journal_mine.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_journal_mine.py`
Expected: `PASS journal_mine`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/journal_mine.py scripts/test_journal_mine.py
git commit -m "feat(insight): tolerant journal TODO-section extraction"
```

---

### Task 2: `insight/geo.py` — location normalization + clustering

**Files:**
- Create: `looki_mcp/insight/geo.py`
- Test: `scripts/test_geo.py`

**Interfaces:**
- Produces:
  - `def normalize_location(value) -> str | None` — lowercased, whitespace-collapsed, trailing-punctuation-stripped; `None` for null/empty/non-str.
  - `def cluster_locations(values: list) -> dict` → `{"places": [{"name": str, "key": str, "count": int}], "unknown_count": int}`. Groups by `normalize_location` key (exact-normalized match); `name` is the most common original spelling in the cluster; `places` sorted by `count` desc; `unknown_count` = number of null/empty entries.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_geo.py
"""Unit tests for insight.geo (pure). Run: .venv/bin/python scripts/test_geo.py"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.insight.geo import normalize_location, cluster_locations  # noqa: E402

def test_normalize():
    assert normalize_location("  Blue Bottle Coffee.  ") == "blue bottle coffee"
    assert normalize_location("BLUE BOTTLE coffee") == "blue bottle coffee"
    assert normalize_location("") is None
    assert normalize_location(None) is None
    assert normalize_location(123) is None

def test_cluster_groups_and_counts():
    out = cluster_locations(["Blue Bottle", "blue bottle", None, "Home", "Home", "Home", ""])
    # Home (3) ranks above Blue Bottle (2); 2 unknowns (None + "")
    assert out["unknown_count"] == 2, out
    names = [(p["name"], p["count"]) for p in out["places"]]
    assert names[0] == ("Home", 3), names
    assert ("Blue Bottle", 2) in names, names

def test_name_is_most_common_spelling():
    out = cluster_locations(["the gym", "The Gym", "The Gym"])
    assert len(out["places"]) == 1
    assert out["places"][0]["name"] == "The Gym" and out["places"][0]["count"] == 3

def main():
    test_normalize(); test_cluster_groups_and_counts(); test_name_is_most_common_spelling()
    print("\033[32mPASS\033[0m geo")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_geo.py`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/insight/geo.py
"""Location-string normalization + heuristic clustering (zero-LLM).

Looki `location` is free-text on `cover_file`/files and is often null. This groups
spellings of the same place by a normalized key (exact-normalized match — the
simplest correct heuristic; fuzzier merging is an optional LLM upgrade, deferred).
Null/empty locations are counted separately as `unknown`.
"""
from __future__ import annotations

import re
from collections import Counter

_WS_RE = re.compile(r"\s+")


def normalize_location(value) -> str | None:
    if not isinstance(value, str):
        return None
    s = _WS_RE.sub(" ", value.strip()).strip(" .,;:-")
    return s.lower() or None


def cluster_locations(values: list) -> dict:
    # key -> list of original spellings (only non-null)
    groups: dict[str, list[str]] = {}
    unknown = 0
    for v in values:
        key = normalize_location(v)
        if key is None:
            unknown += 1
            continue
        groups.setdefault(key, []).append(v.strip())
    places = []
    for key, spellings in groups.items():
        name = Counter(spellings).most_common(1)[0][0]
        places.append({"name": name, "key": key, "count": len(spellings)})
    places.sort(key=lambda p: p["count"], reverse=True)
    return {"places": places, "unknown_count": unknown}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_geo.py`
Expected: `PASS geo`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/geo.py scripts/test_geo.py
git commit -m "feat(insight): location normalization + clustering"
```

---

### Task 3: `commitment_harvester` tool

**Files:**
- Create: `looki_mcp/tools/insight_productivity.py`
- Test: `scripts/test_commitment_harvester.py`

**Interfaces:**
- Consumes: `journal_mine.extract_todo_section` (Task 1); `insight.scan.walk_journals` (PR1); `insight.envelope.render` (PR1); `looki_mcp.tools.journals._flatten_buckets` (existing); `client.get_client` (existing); `insight.llm` (PR1).
- Produces: registered tool `commitment_harvester(days=14)`. Pure transform `_harvest_commitments(entries: list[dict]) -> dict` → `{"by_date": {date: [{"text", "type", "entry_id", "parsed_section"}]}, "total": int, "unparsed_entries": int}`. Module-level `register_productivity_tools(mcp)`.

- [ ] **Step 1: Write the failing test (pure transform + envelope wiring)**

```python
# scripts/test_commitment_harvester.py
"""Tests for commitment_harvester: pure transform + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_commitment_harvester.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.tools.insight_productivity as prod  # noqa: E402

def test_harvest_groups_by_date_and_flags():
    entries = [
        {"id": "e1", "type": "YESTERDAY_RECAP", "date": "2026-06-20",
         "content": "Actionable Suggestions\n- Email Bob\n- Pay rent"},
        {"id": "e2", "type": "DIARY", "date": "2026-06-20", "content": "- not a commitment heading"},
        {"id": "e3", "type": "AUDIO_SUMMARY", "date": "2026-06-19",
         "content": "Discussion notes\nTODO: follow up with Sarah"},
    ]
    out = prod._harvest_commitments(entries)
    # DIARY entry is ignored (only YESTERDAY_RECAP/AUDIO_SUMMARY mined)
    assert out["total"] == 3, out
    assert [c["text"] for c in out["by_date"]["2026-06-20"]] == ["Email Bob", "Pay rent"]
    assert out["by_date"]["2026-06-20"][0]["parsed_section"] is True
    assert out["by_date"]["2026-06-19"][0]["text"] == "follow up with Sarah"
    assert out["by_date"]["2026-06-19"][0]["parsed_section"] is False  # fallback path

def test_tool_wraps_in_envelope():
    async def fake_gather(days):
        return ([{"id": "e1", "type": "YESTERDAY_RECAP", "date": "2026-06-20",
                  "content": "TODOs\n- ship it"}],
                {"calls_used": 1, "days_scanned": days, "capped": None})
    prod._gather_journal_entries = fake_gather  # type: ignore
    out = json.loads(asyncio.run(prod._commitment_harvester_impl(days=7)))
    assert out["data"]["total"] == 1
    assert out["data"]["by_date"]["2026-06-20"][0]["text"] == "ship it"
    assert out["narrative"] is None              # no LLM configured
    assert out["meta"]["calls_used"] == 1 and out["meta"]["days_scanned"] == 7

def main():
    test_harvest_groups_by_date_and_flags()
    test_tool_wraps_in_envelope()
    print("\033[32mPASS\033[0m commitment_harvester")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_commitment_harvester.py`
Expected: `ModuleNotFoundError: looki_mcp.tools.insight_productivity`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/tools/insight_productivity.py
"""Productivity insight tools. commitment_harvester mines TODO/Actionable sections
out of YESTERDAY_RECAP + AUDIO_SUMMARY journals — a to-do list built from your own
life. LLM-free core (the text is already in the journal body); an optional LLM
narrative summarizes when a provider is configured.
"""
from __future__ import annotations

import math

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client
from looki_mcp.insight import llm
from looki_mcp.insight.envelope import render
from looki_mcp.insight.journal_mine import extract_todo_section
from looki_mcp.insight.scan import walk_journals
from looki_mcp.tools.journals import _flatten_buckets

_MINED_TYPES = {"YESTERDAY_RECAP", "AUDIO_SUMMARY"}


def _harvest_commitments(entries: list[dict]) -> dict:
    by_date: dict[str, list[dict]] = {}
    unparsed = 0
    for entry in entries:
        if entry.get("type") not in _MINED_TYPES:
            continue
        section = extract_todo_section(entry)
        if not section["parsed_section"]:
            unparsed += 1
        date = entry.get("date") or entry.get("bucket_date") or "undated"
        for text in section["items"]:
            by_date.setdefault(date, []).append({
                "text": text,
                "type": entry.get("type"),
                "entry_id": entry.get("id"),
                "parsed_section": section["parsed_section"],
            })
    return {"by_date": by_date, "total": len(entries), "unparsed_entries": unparsed}


async def _gather_journal_entries(days: int) -> tuple[list[dict], dict]:
    max_calls = math.ceil(days / 31) + 1
    async with get_client() as client:
        result = await walk_journals(client, cursor_date=None, max_days=days, max_calls=max_calls)
    entries = _flatten_buckets({"items": result["items"]})
    meta = {"calls_used": result["calls_used"], "days_scanned": days, "capped": result["capped"]}
    return entries, meta


async def _commitment_harvester_impl(days: int = 14) -> str:
    if not (1 <= days <= 90):
        return "Error: days must be between 1 and 90."
    try:
        entries, meta = await _gather_journal_entries(days)
        data = _harvest_commitments(entries)
        narrative = None
        if llm.llm_configured() and data["total"]:
            narrative = await llm.synthesize(
                "You summarize a personal to-do list extracted from journal entries. Be terse.",
                f"Open commitments by date: {data['by_date']}",
            )
        return render(data, narrative=narrative, meta=meta)
    except Exception as exc:
        return f"Error: {format_error(exc)}"


def register_productivity_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def commitment_harvester(days: int = 14) -> str:
        """
        Builds a to-do list mined from your own life: extracts the Actionable
        Suggestions / TODO lines out of your recent YESTERDAY_RECAP and AUDIO_SUMMARY
        journal entries, grouped by date. Works with no LLM configured (the text is
        already in the journals). Use for "what did I say I'd do?" / "open commitments".

        Args:
            days: How many days back to scan. Between 1 and 90, default 14.
        """
        return await _commitment_harvester_impl(days=days)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_commitment_harvester.py`
Expected: `PASS commitment_harvester`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/tools/insight_productivity.py scripts/test_commitment_harvester.py
git commit -m "feat(tools): commitment_harvester (LLM-free TODO mining)"
```

---

### Task 4: `the_unwritten` tool

**Files:**
- Create: `looki_mcp/tools/insight_memory.py`
- Test: `scripts/test_the_unwritten.py`

**Interfaces:**
- Consumes: `iter_dates` (PR1 scan); `client.get_client`/`governed_get`/`unwrap`; `_flatten_buckets` (existing); `envelope.render`; `insight.llm`.
- Produces: registered tool `the_unwritten(days=14, min_significance=2)`. Pure transform `_diff_unwritten(moment_days: list[dict], journal_entries: list[dict], min_significance: int) -> dict` → `{"unwritten": [moment...], "total_moments": int, "written_dates": int}`. A date D is "covered" if any journal entry covers it (entry `date == D`, or for multi-day entries `bucket_start_date <= D <= date`). Moments on uncovered dates with `significance >= min_significance` are "unwritten". Significance = `1 + (len(media_types)>=2) + (duration_seconds>=300) + (cover_file.location present)`. Module-level `register_memory_tools(mcp)`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_the_unwritten.py
"""Tests for the_unwritten: pure diff + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_the_unwritten.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.tools.insight_memory as mem  # noqa: E402

def _moment(mid, date, *, media=("IMAGE",), start="T10:00:00", end="T10:20:00", loc="Park"):
    return {"id": mid, "date": date, "media_types": list(media),
            "start_time": f"{date}{start}+00:00", "end_time": f"{date}{end}+00:00",
            "cover_file": {"location": loc}, "title": f"m{mid}"}

def test_significance_and_coverage():
    moment_days = [
        {"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]},   # uncovered -> unwritten
        {"date": "2026-06-21", "moments": [_moment("b", "2026-06-21")]},   # covered by single-day journal
        {"date": "2026-06-22", "moments": [_moment("c", "2026-06-22")]},   # covered by multi-day storyboard
    ]
    journal_entries = [
        {"id": "j1", "type": "DIARY", "date": "2026-06-21", "bucket_date": "2026-06-21", "bucket_start_date": None},
        {"id": "j2", "type": "STORYBOARD", "date": "2026-06-23", "bucket_date": "2026-06-23", "bucket_start_date": "2026-06-22"},
    ]
    out = mem._diff_unwritten(moment_days, journal_entries, min_significance=2)
    ids = [m["id"] for m in out["unwritten"]]
    assert ids == ["a"], ids  # only 2026-06-20 uncovered
    assert out["total_moments"] == 3

def test_min_significance_filters():
    # A trivial moment (1 image, short, no location) scores 1; min_significance=2 drops it.
    md = [{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20", media=("IMAGE",), start="T10:00:00", end="T10:01:00", loc=None)]}]
    out = mem._diff_unwritten(md, [], min_significance=2)
    assert out["unwritten"] == [], out

def test_tool_envelope():
    async def fake_gather(days):
        return ([{"date": "2026-06-20", "moments": [_moment("a", "2026-06-20")]}], [],
                {"calls_used": 2, "days_scanned": days, "capped": None})
    mem._gather_unwritten = fake_gather  # type: ignore
    out = json.loads(asyncio.run(mem._the_unwritten_impl(days=7, min_significance=2)))
    assert [m["id"] for m in out["data"]["unwritten"]] == ["a"]
    assert out["narrative"] is None and out["meta"]["calls_used"] == 2

def main():
    test_significance_and_coverage(); test_min_significance_filters(); test_tool_envelope()
    print("\033[32mPASS\033[0m the_unwritten")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_the_unwritten.py`
Expected: `ModuleNotFoundError: looki_mcp.tools.insight_memory`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/tools/insight_memory.py
"""Memory/retrospective insight tools. the_unwritten finds the moments you captured
that the AI never journaled — the gaps in your story. Pure data diff (LLM-free core);
an optional LLM pass can rank/explain when a provider is configured.
"""
from __future__ import annotations

from datetime import datetime

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, governed_get, unwrap
from looki_mcp.insight import llm
from looki_mcp.insight.envelope import render
from looki_mcp.insight.scan import iter_dates
from looki_mcp.tools.convenience import _days_ago_local, _today_local
from looki_mcp.tools.journals import _flatten_buckets

# Bound the per-tool Looki call budget: one /moments + one /journals per day, + slack.
_MAX_CALLS_PER_DAY = 2


def _duration_seconds(moment: dict) -> float:
    try:
        start = datetime.fromisoformat(moment["start_time"])
        end = datetime.fromisoformat(moment["end_time"])
        return max(0.0, (end - start).total_seconds())
    except Exception:
        return 0.0


def _significance(moment: dict) -> int:
    score = 1
    if len(moment.get("media_types") or []) >= 2:
        score += 1
    if _duration_seconds(moment) >= 300:
        score += 1
    cover = moment.get("cover_file") or {}
    if cover.get("location"):
        score += 1
    return score


def _covered_dates(journal_entries: list[dict]) -> set[str]:
    """Dates that have a covering journal entry, expanding multi-day buckets to ranges."""
    covered: set[str] = set()
    for entry in journal_entries:
        end = entry.get("bucket_date") or entry.get("date")
        start = entry.get("bucket_start_date") or end
        if not end:
            continue
        if start and start <= end:
            for d in iter_dates(start, end):
                covered.add(d)
        else:
            covered.add(end)
    return covered


def _diff_unwritten(moment_days: list[dict], journal_entries: list[dict], min_significance: int) -> dict:
    covered = _covered_dates(journal_entries)
    unwritten: list[dict] = []
    total = 0
    for day in moment_days:
        date = day.get("date")
        for moment in day.get("moments") or []:
            total += 1
            if date in covered:
                continue
            if _significance(moment) >= min_significance:
                unwritten.append({
                    "id": moment.get("id"), "date": date, "title": moment.get("title"),
                    "significance": _significance(moment),
                    "media_types": moment.get("media_types"),
                    "location": (moment.get("cover_file") or {}).get("location"),
                })
    return {"unwritten": unwritten, "total_moments": total, "written_dates": len(covered)}


async def _gather_unwritten(days: int) -> tuple[list[dict], list[dict], dict]:
    start, end = _days_ago_local(days), _today_local()
    dates = iter_dates(start, end)
    moment_days: list[dict] = []
    journal_entries: list[dict] = []
    calls = 0
    async with get_client() as client:
        for d in dates:
            resp = await governed_get(client, "/moments", params={"on_date": d})
            calls += 1
            data = unwrap(resp)
            moment_days.append({"date": d, "moments": data if isinstance(data, list) else []})
            jresp = await governed_get(client, "/journals/by_date", params={"on_date": d})
            calls += 1
            journal_entries.extend(_flatten_buckets(unwrap(jresp)))
    meta = {"calls_used": calls, "days_scanned": len(dates), "capped": None}
    return moment_days, journal_entries, meta


async def _the_unwritten_impl(days: int = 14, min_significance: int = 2) -> str:
    if not (1 <= days <= 31):
        return "Error: days must be between 1 and 31."
    if not (1 <= min_significance <= 4):
        return "Error: min_significance must be between 1 and 4."
    try:
        moment_days, journal_entries, meta = await _gather_unwritten(days)
        data = _diff_unwritten(moment_days, journal_entries, min_significance)
        narrative = None
        if llm.llm_configured() and data["unwritten"]:
            narrative = await llm.synthesize(
                "You note which captured moments the AI diary skipped. Be brief and warm.",
                f"Unwritten moments: {data['unwritten']}",
            )
        return render(data, narrative=narrative, meta=meta)
    except Exception as exc:
        return f"Error: {format_error(exc)}"


def register_memory_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def the_unwritten(days: int = 14, min_significance: int = 2) -> str:
        """
        Finds the significant moments you captured that the AI never wrote a journal
        entry about — the gaps in your story. Works with no LLM configured. Use for
        "what did my diary miss?" or to resurface overlooked days.

        Args:
            days: How many days back to compare. Between 1 and 31, default 14.
            min_significance: Minimum significance (1-4: media richness, duration,
                location) for a moment to count. Default 2.
        """
        return await _the_unwritten_impl(days=days, min_significance=min_significance)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_the_unwritten.py`
Expected: `PASS the_unwritten`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/tools/insight_memory.py scripts/test_the_unwritten.py
git commit -m "feat(tools): the_unwritten (captured-but-unjournaled diff)"
```

---

### Task 5: `places_of_my_life` tool

**Files:**
- Create: `looki_mcp/tools/insight_places.py`
- Test: `scripts/test_places_of_my_life.py`

**Interfaces:**
- Consumes: `geo.normalize_location` (Task 2); `iter_dates` (PR1); `client.get_client`/`governed_get`/`unwrap`; `envelope.render`; `insight.llm`; `convenience._today_local`/`_days_ago_local`.
- Produces: registered tool `places_of_my_life(days=30, top_n=15, deep=False)`. Pure transform `_rank_places(moments: list[dict], top_n: int) -> dict` → `{"places": [{"name", "key", "visits", "total_seconds", "sample_moment": {id,title,date}}], "unknown_count": int, "total_moments": int}`, ranked by `visits` desc then `total_seconds` desc. Module-level `register_places_tools(mcp)`. `deep=True` adds a `meta` note that per-moment `/files` harvest is not yet wired (PR3) — for PR2 it behaves like default and sets `meta.capped=None` with a `deep_pending` note in `data`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_places_of_my_life.py
"""Tests for places_of_my_life: pure ranking + envelope wiring (no network/LLM).
Run: .venv/bin/python scripts/test_places_of_my_life.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.tools.insight_places as places  # noqa: E402

def _m(mid, date, loc, start, end, title="t"):
    return {"id": mid, "date": date, "title": title,
            "start_time": f"{date}T{start}+00:00", "end_time": f"{date}T{end}+00:00",
            "cover_file": {"location": loc}}

def test_rank_by_visits_then_time():
    moments = [
        _m("1", "2026-06-01", "Home", "08:00:00", "08:30:00"),
        _m("2", "2026-06-02", "Home", "09:00:00", "10:00:00"),
        _m("3", "2026-06-02", "Cafe", "12:00:00", "13:00:00"),
        _m("4", "2026-06-03", None, "14:00:00", "14:10:00"),   # unknown location
    ]
    out = places._rank_places(moments, top_n=10)
    assert out["unknown_count"] == 1 and out["total_moments"] == 4
    names = [(p["name"], p["visits"]) for p in out["places"]]
    assert names[0] == ("Home", 2), names         # Home has 2 visits, ranks first
    assert ("Cafe", 1) in names
    home = next(p for p in out["places"] if p["name"] == "Home")
    assert home["total_seconds"] == 1800 + 3600    # 30min + 60min
    assert home["sample_moment"]["id"] in ("1", "2")

def test_top_n_truncates():
    moments = [_m(str(i), "2026-06-01", f"place{i}", "08:00:00", "08:10:00") for i in range(5)]
    out = places._rank_places(moments, top_n=3)
    assert len(out["places"]) == 3

def test_tool_envelope():
    async def fake_gather(days, deep):
        return ([_m("1", "2026-06-01", "Home", "08:00:00", "08:30:00")],
                {"calls_used": 1, "days_scanned": days, "capped": None})
    places._gather_place_moments = fake_gather  # type: ignore
    out = json.loads(asyncio.run(places._places_of_my_life_impl(days=30, top_n=15, deep=False)))
    assert out["data"]["places"][0]["name"] == "Home"
    assert out["narrative"] is None and out["meta"]["days_scanned"] == 30

def main():
    test_rank_by_visits_then_time(); test_top_n_truncates(); test_tool_envelope()
    print("\033[32mPASS\033[0m places_of_my_life")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_places_of_my_life.py`
Expected: `ModuleNotFoundError: looki_mcp.tools.insight_places`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/tools/insight_places.py
"""Geo insight tools. places_of_my_life ranks the places your life actually happens
at, from the `location` on each day's moment cover files — a map of your life no
single endpoint exposes. LLM-free; default mode is one /moments call per day.
"""
from __future__ import annotations

from datetime import datetime

from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, governed_get, unwrap
from looki_mcp.insight import llm
from looki_mcp.insight.envelope import render
from looki_mcp.insight.geo import normalize_location
from looki_mcp.insight.scan import iter_dates
from looki_mcp.tools.convenience import _days_ago_local, _today_local


def _duration_seconds(moment: dict) -> float:
    try:
        start = datetime.fromisoformat(moment["start_time"])
        end = datetime.fromisoformat(moment["end_time"])
        return max(0.0, (end - start).total_seconds())
    except Exception:
        return 0.0


def _rank_places(moments: list[dict], top_n: int) -> dict:
    agg: dict[str, dict] = {}
    unknown = 0
    for moment in moments:
        loc = (moment.get("cover_file") or {}).get("location")
        key = normalize_location(loc)
        if key is None:
            unknown += 1
            continue
        place = agg.setdefault(key, {"key": key, "spellings": [], "visits": 0,
                                     "total_seconds": 0.0, "sample_moment": None})
        place["spellings"].append(loc.strip())
        place["visits"] += 1
        place["total_seconds"] += _duration_seconds(moment)
        if place["sample_moment"] is None:
            place["sample_moment"] = {"id": moment.get("id"), "title": moment.get("title"), "date": moment.get("date")}
    from collections import Counter
    ranked = sorted(agg.values(), key=lambda p: (p["visits"], p["total_seconds"]), reverse=True)
    places = [{
        "name": Counter(p["spellings"]).most_common(1)[0][0],
        "key": p["key"], "visits": p["visits"],
        "total_seconds": round(p["total_seconds"]),
        "sample_moment": p["sample_moment"],
    } for p in ranked[:top_n]]
    return {"places": places, "unknown_count": unknown, "total_moments": len(moments)}


async def _gather_place_moments(days: int, deep: bool) -> tuple[list[dict], dict]:
    start, end = _days_ago_local(days), _today_local()
    dates = iter_dates(start, end)
    moments: list[dict] = []
    calls = 0
    async with get_client() as client:
        for d in dates:
            resp = await governed_get(client, "/moments", params={"on_date": d})
            calls += 1
            data = unwrap(resp)
            if isinstance(data, list):
                moments.extend(data)
    meta = {"calls_used": calls, "days_scanned": len(dates), "capped": None}
    return moments, meta


async def _places_of_my_life_impl(days: int = 30, top_n: int = 15, deep: bool = False) -> str:
    if not (1 <= days <= 90):
        return "Error: days must be between 1 and 90."
    if not (1 <= top_n <= 50):
        return "Error: top_n must be between 1 and 50."
    try:
        moments, meta = await _gather_place_moments(days, deep)
        data = _rank_places(moments, top_n)
        # Per-moment /files location harvest (deep mode) lands in PR3; flag the request.
        if deep:
            data["deep_pending"] = "Per-moment /files location harvest is not yet wired (PR3); using cover_file locations."
        narrative = None
        if llm.llm_configured() and data["places"]:
            narrative = await llm.synthesize(
                "You describe where someone spends their life from a ranked place list. Be vivid but brief.",
                f"Top places: {[(p['name'], p['visits']) for p in data['places']]}",
            )
        return render(data, narrative=narrative, meta=meta)
    except Exception as exc:
        return f"Error: {format_error(exc)}"


def register_places_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def places_of_my_life(days: int = 30, top_n: int = 15, deep: bool = False) -> str:
        """
        Ranks the places your life actually happens at — by visit frequency and time
        spent — from the locations tagged on your moments, with a representative memory
        per place. A map of your life. Works with no LLM configured.

        Args:
            days: How many days back to scan. Between 1 and 90, default 30.
            top_n: How many top places to return. Between 1 and 50, default 15.
            deep: Reserved for finer per-moment location harvest (PR3); currently uses
                each moment's cover location.
        """
        return await _places_of_my_life_impl(days=days, top_n=top_n, deep=deep)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_places_of_my_life.py`
Expected: `PASS places_of_my_life`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/tools/insight_places.py scripts/test_places_of_my_life.py
git commit -m "feat(tools): places_of_my_life (cover-location place ranking)"
```

---

### Task 6: Register the 3 tools + bump count

**Files:**
- Modify: `looki_mcp/server.py` (imports, `TOOL_COUNT`, register calls, `instructions`)
- Test: `scripts/test_tool_count.py`

**Interfaces:**
- Consumes: `register_productivity_tools` (Task 3), `register_memory_tools` (Task 4), `register_places_tools` (Task 5).
- Produces: `TOOL_COUNT = 27`; the three new tools registered; updated server `instructions`.

- [ ] **Step 1: Write the failing test** — assert the running tool registry exposes exactly `TOOL_COUNT` tools, including the three new names.

```python
# scripts/test_tool_count.py
"""Asserts server registers TOOL_COUNT tools incl. the 3 PR2 insight tools (no network).
Run: .venv/bin/python scripts/test_tool_count.py
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.server import mcp, TOOL_COUNT  # noqa: E402

def test_count_and_new_tools():
    tools = asyncio.run(mcp.get_tools())   # fastmcp: dict[name -> Tool]
    names = set(tools)
    assert len(names) == TOOL_COUNT, f"{len(names)} registered vs TOOL_COUNT={TOOL_COUNT}: {sorted(names)}"
    for t in ("commitment_harvester", "the_unwritten", "places_of_my_life"):
        assert t in names, f"missing {t}"
    assert TOOL_COUNT == 27

def main():
    test_count_and_new_tools()
    print("\033[32mPASS\033[0m tool_count")

if __name__ == "__main__":
    main()
```

(Note: if `mcp.get_tools()` is not the correct fastmcp accessor in the installed version, discover the right one — e.g. `await mcp.list_tools()` or `mcp._tool_manager.list_tools()` — by checking the installed `fastmcp` API; the assertion logic stays the same. Report the accessor used in your report.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_tool_count.py`
Expected: FAIL — the 3 tools aren't registered and `TOOL_COUNT` is still 24.

- [ ] **Step 3: Write minimal implementation** — edit `looki_mcp/server.py`:

Add imports near the other tool imports (after line 19):
```python
from looki_mcp.tools.insight_productivity import register_productivity_tools
from looki_mcp.tools.insight_memory import register_memory_tools
from looki_mcp.tools.insight_places import register_places_tools
```

Bump the count:
```python
TOOL_COUNT = 27
```

Add the registration calls after `register_convenience_tools(mcp)` (line 77):
```python
register_productivity_tools(mcp)
register_memory_tools(mcp)
register_places_tools(mcp)
```

Extend the `instructions=(...)` string with one sentence documenting the new tools and the envelope split (append inside the parenthesized string, before the closing `)`):
```python
        " Insight tools (commitment_harvester, the_unwritten, places_of_my_life) "
        "combine multiple endpoints and return a {data, narrative, meta} envelope "
        "(narrative is filled only when an LLM provider is configured); the other "
        "tools return raw API JSON."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_tool_count.py`
Expected: `PASS tool_count`.

- [ ] **Step 5: Run the full PR2 + regression suite, then commit**

```bash
for t in journal_mine geo commitment_harvester the_unwritten places_of_my_life tool_count journals_helpers; do .venv/bin/python scripts/test_${t}.py; done
git add looki_mcp/server.py scripts/test_tool_count.py
git commit -m "feat(server): register PR2 insight tools (24 -> 27)"
```

---

## Self-Review

**Spec coverage (PR2 scope):**
- `commitment_harvester` §4.3 → Task 3 ✓ (tolerant TODO mining, LLM-free core, optional narrative).
- `the_unwritten` §4.10 → Task 4 ✓ (multi-bucket coverage via `_flatten_buckets` + `[start_date,date]` range, significance heuristic [m2]).
- `places_of_my_life` §4.2 → Task 5 ✓ (cover_file-location default; `deep` flagged-pending [B1]).
- `journal_mine` §3.6 → Task 1 ✓ (tolerant + `parsed_section` [B3]); `extract_people` deferred to PR3 (consumer is PR3's people tool).
- `geo` §3.3 → Task 2 ✓.
- Registration / count / instructions split [m1] → Task 6 ✓.
- `temporal.py` (§3.4) and durable hero capture (§3.7) intentionally deferred to PR3 (their consumers are PR3) — stated in Global Constraints.

**Placeholder scan:** no "TBD"/"add error handling"/"similar to Task N" — every step has real code. The one runtime-API caveat (fastmcp tool-registry accessor in Task 6) gives a concrete fallback + reporting instruction rather than a vague placeholder.

**Type consistency:** `extract_todo_section(entry)->{items,parsed_section,candidate_lines}` is consumed with those exact keys in Task 3. `_gather_*` return tuples `(data..., meta)` match each `_*_impl` consumer. `render(data, narrative=, meta=)` matches PR1's signature. `_flatten_buckets({"items": [...]})` matches the existing function (handles dict `{items}` and bare list). `meta` dicts always carry `calls_used/days_scanned/capped` (envelope fills the rest).

---

## Execution Handoff

PR3 (deep + vision tools: `on_this_day_rewind`, `life_rhythm`, `what_was_different`, `people_and_meetings_intel`, `visual_search`, `auto_biography_chapter`, `year_in_review`, plus `temporal.py`, `extract_people`, `cache.capture_hero_image`, and the **governor-for-VLM prerequisite** flagged by PR1's final review) gets its own plan after PR2 lands.
