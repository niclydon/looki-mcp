"""Memory/retrospective insight tools. the_unwritten finds the moments you captured
that the AI never journaled — the gaps in your story. Pure data diff (LLM-free core);
an optional LLM pass can explain when a provider is configured.

Coverage is date-level: a moment counts as written when its date (or a multi-day
range) carries an event-level written journal entry. Covering types (contract
verified 2026-11-09, journals_api_findings.md): DIARY (atomic event vignettes),
AUDIO_SUMMARY / MANUAL_AUDIO_SUMMARY (heard-speech recaps), and STORYBOARD
(multi-day, covers its start_date..date range). Media-only types (DAILY_VLOG,
DAILY_HEALTH_REPORT, PLOG, COMIC_PAGE) and day-level digests (YESTERDAY_RECAP,
DIETARY, WEEKLY_JOURNAL) do not mark a day as written.

Journals are read from the paged GET /journals feed (GET /journals/by_date was
retired upstream 2026-11-09). Moment text (description, audio_summary) is returned
in full; audio_summary goes through the shared normalizer.
"""
from __future__ import annotations

import math
from datetime import datetime

from fastmcp import FastMCP

from looki_mcp.audio_summary import normalize_audio_summary
from looki_mcp.client import format_error, get_client, governed_get, unwrap
from looki_mcp.insight import llm
from looki_mcp.insight.envelope import render
from looki_mcp.insight.scan import iter_dates, walk_journals
from looki_mcp.tools.convenience import _days_ago_local, _today_local
from looki_mcp.tools.journals import _flatten_buckets

_COVERING_TYPES = ("DIARY", "AUDIO_SUMMARY", "MANUAL_AUDIO_SUMMARY", "STORYBOARD")


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
    """Dates with a covering journal entry, expanding multi-day entries to ranges."""
    covered: set[str] = set()
    for entry in journal_entries:
        if entry.get("type") not in _COVERING_TYPES:
            continue
        end = entry.get("date") or entry.get("bucket_date")
        start = entry.get("start_date") or entry.get("bucket_start_date") or end
        if not end:
            continue
        end, start = end[:10], (start or end)[:10]
        if start <= end:
            covered.update(iter_dates(start, end))
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
            if not isinstance(moment, dict):
                continue
            total += 1
            if date in covered:
                continue
            significance = _significance(moment)
            if significance >= min_significance:
                item = {
                    "id": moment.get("id"), "date": date, "title": moment.get("title"),
                    "description": moment.get("description"),
                    "significance": significance,
                    "media_types": moment.get("media_types"),
                    "location": (moment.get("cover_file") or {}).get("location"),
                    "start_time": moment.get("start_time"),
                    "end_time": moment.get("end_time"),
                }
                if "audio_summary" in moment:
                    item["audio_summary"] = normalize_audio_summary(moment["audio_summary"])
                unwritten.append(item)
    return {
        "unwritten": unwritten,
        "total_moments": total,
        "written_dates": len(covered),
        "covering_types": list(_COVERING_TYPES),
    }


async def _gather_unwritten(days: int) -> tuple[list[dict], list[dict], dict]:
    start, end = _days_ago_local(days), _today_local()
    dates = iter_dates(start, end)
    moment_days: list[dict] = []
    calls = 0
    async with get_client() as client:
        for d in dates:
            resp = await governed_get(client, "/moments", params={"on_date": d})
            calls += 1
            data = unwrap(resp)
            moment_days.append({"date": d, "moments": data if isinstance(data, list) else []})
        # +1 day of slack so a journal dated the morning after still pages in.
        journal_days = len(dates) + 1
        result = await walk_journals(
            client, cursor_date=None, max_days=journal_days,
            max_calls=math.ceil(journal_days / 31) + 1,
        )
        calls += result["calls_used"]
    journal_entries = _flatten_buckets({"items": result["items"]})
    meta = {"calls_used": calls, "days_scanned": len(dates), "capped": result["capped"]}
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


def register_insight_memory_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def the_unwritten(days: int = 14, min_significance: int = 2) -> str:
        """
        Finds the significant moments you captured on days the AI never wrote an
        event-level journal entry about (DIARY / audio summary / storyboard) — the
        gaps in your story. Each moment comes back with its full description and
        normalized audio_summary. Works with no LLM configured. Use for "what did my
        diary miss?" or to resurface overlooked days. Returns a {data, narrative, meta}
        envelope; narrative is null without an LLM provider.

        Args:
            days: How many days back to compare. Between 1 and 31, default 14.
            min_significance: Minimum significance (1-4: media richness, duration,
                location) for a moment to count. Default 2.
        """
        return await _the_unwritten_impl(days=days, min_significance=min_significance)
