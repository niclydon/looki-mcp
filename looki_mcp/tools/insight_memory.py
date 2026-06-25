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
