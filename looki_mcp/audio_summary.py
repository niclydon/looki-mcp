"""Normalize the two audio_summary payload shapes seen from Looki moments.

Looki content is never truncated in this server (operator rule, 2026-11-09):
the summary/detail distinction that used to bound summary-mode text at 600
chars is gone. `summary` is accepted for call-site compatibility and ignored;
every mode returns the complete value. `truncated` is always False and is
kept only so the {text, topics, truncated} shape stays stable for consumers.
"""

from __future__ import annotations

import json
from typing import Any


def normalize_audio_summary(value: Any, *, summary: bool = False) -> dict[str, Any] | None:
    """Return a stable {text, topics, truncated} shape with the full value."""
    if value is None:
        return None

    structured: Any = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("topics"), list):
            structured = parsed

    if isinstance(structured, dict) and isinstance(structured.get("topics"), list):
        text_value = next(
            (structured.get(key) for key in ("text", "summary", "content")
             if isinstance(structured.get(key), str)),
            None,
        )
        topics = structured["topics"]
    elif isinstance(value, str):
        text_value = value
        topics = []
    else:
        # Preserve an unrecognized upstream shape as text for visibility.
        text_value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        topics = []

    return {"text": text_value, "topics": topics, "truncated": False}


def normalize_moment_payload(value: Any, *, summary: bool = False) -> Any:
    """Copy nested API payloads, normalizing every moment audio_summary field."""
    if isinstance(value, list):
        return [normalize_moment_payload(item, summary=summary) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: normalize_moment_payload(item, summary=summary)
        for key, item in value.items()
        if key != "audio_summary"
    }
    if "audio_summary" in value:
        result["audio_summary"] = normalize_audio_summary(value["audio_summary"], summary=summary)
    return result
