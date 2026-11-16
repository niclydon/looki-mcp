"""Productivity insight tools. commitment_harvester mines the follow-up sections
out of YESTERDAY_RECAP and audio-summary journals: a to-do list built from your own
life. LLM-free core (the text is already in the journal body); an optional LLM
narrative summarizes when a provider is configured.

Journal types mined (contract verified 2026-11-09, journals_api_findings.md): the
text types whose `content` is present and non-null and carries actionable prose:
YESTERDAY_RECAP (``### Suggestions for Today``, older ``Actionable Suggestions`` /
``TODOs``), AUDIO_SUMMARY and MANUAL_AUDIO_SUMMARY (``### Action items``). DIARY
vignettes (~100-180c event descriptions) are not mined. An entry with no
recognised section contributes only explicit ``TODO:`` lines; its other bullets
are narration and are counted, not returned (OB-70149). Item text is returned in
full; Looki content is never truncated here.

Counters in ``data``:
- ``commitment_count``: commitment items returned in ``by_date``.
- ``total``: the same number, kept as the envelope's item count.
- ``entries_scanned``: journal entries the feed returned, all types.
- ``mined_entries``: distinct entries of a mined type.
- ``unparsed_entries`` / ``unparsed_entry_ids``: mined entries with no recognised
  follow-up section.
- ``unsectioned_line_count``: list lines in those entries left out as narration.
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

_MINED_TYPES = {"YESTERDAY_RECAP", "AUDIO_SUMMARY", "MANUAL_AUDIO_SUMMARY"}


def _harvest_commitments(entries: list[dict]) -> dict:
    by_date: dict[str, list[dict]] = {}
    unparsed_ids: list = []
    unsectioned_lines = 0
    mined = 0
    seen: set = set()
    for entry in entries:
        if entry.get("type") not in _MINED_TYPES:
            continue
        eid = entry.get("id")
        if eid is not None:
            # A date can yield multiple buckets; never mine one entry twice.
            if eid in seen:
                continue
            seen.add(eid)
        mined += 1
        section = extract_todo_section(entry)
        if not section["parsed_section"]:
            unparsed_ids.append(eid)
            unsectioned_lines += len(section["fallback_lines"])
        date = entry.get("date") or entry.get("bucket_date") or "undated"
        source = "section" if section["parsed_section"] else "todo_line"
        for text in section["items"]:
            by_date.setdefault(date, []).append({
                "text": text,
                "type": entry.get("type"),
                "entry_id": eid,
                "title": entry.get("title"),
                "parsed_section": section["parsed_section"],
                "source": source,
            })
    count = sum(len(v) for v in by_date.values())
    return {
        "by_date": by_date,
        "commitment_count": count,
        "total": count,
        "entries_scanned": len(entries),
        "mined_entries": mined,
        "unparsed_entries": len(unparsed_ids),
        "unparsed_entry_ids": unparsed_ids,
        "unsectioned_line_count": unsectioned_lines,
    }


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
        if llm.llm_configured() and data["commitment_count"]:
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
        Builds a to-do list mined from your own life: extracts the follow-up
        sections (recap "Suggestions for Today", audio "Action items", older
        Actionable Suggestions / TODOs) and explicit TODO: lines out of your recent
        YESTERDAY_RECAP, AUDIO_SUMMARY and MANUAL_AUDIO_SUMMARY journal entries,
        grouped by date, each item in full with its source entry id. Narration in
        entries with no follow-up section is counted (unparsed_entries), never
        returned as a commitment. Works with no LLM configured (the text is already in the
        journals). Use for "what did I say I'd do?" / "open commitments". Returns a
        {data, narrative, meta} envelope; narrative is null without an LLM provider.

        Args:
            days: How many days back to scan. Between 1 and 90, default 14.
        """
        return await _commitment_harvester_impl(days=days)
