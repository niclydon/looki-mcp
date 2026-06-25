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
