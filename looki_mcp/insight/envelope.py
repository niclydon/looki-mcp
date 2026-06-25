"""Pure serializer for the {data, narrative, meta} hybrid-output contract.

Intentionally does NOT call the LLM layer — tools synthesize narrative themselves
(via insight.llm.synthesize) and pass the string in. This keeps the LLM dependency
out of every tool's output path and makes the envelope trivially testable.
"""
from __future__ import annotations
import json
from typing import Any

_META_DEFAULTS = {
    "calls_used": 0,
    "days_scanned": 0,
    "capped": None,          # None | "budget" | "rate_limit"
    "cache_hit": False,
    "vlm_used": False,
    "enrichment_skipped_reason": None,
}


def render(data: Any, *, narrative: str | None = None, meta: dict | None = None) -> str:
    merged = {**_META_DEFAULTS, **(meta or {})}
    return json.dumps({"data": data, "narrative": narrative, "meta": merged}, indent=2)
