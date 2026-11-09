"""Normalize the two audio_summary payload shapes seen from Looki moments."""

from __future__ import annotations

import json
from typing import Any

_SUMMARY_TEXT_LIMIT = 600
_SUMMARY_TOPIC_LIMIT = 20
_SUMMARY_TOPIC_TEXT_LIMIT = 200


def normalize_audio_summary(value: Any, *, summary: bool) -> dict[str, Any] | None:
    """Return a stable {text, topics, truncated} shape without losing detail mode."""
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

    truncated = False
    if summary:
        if isinstance(text_value, str) and len(text_value) > _SUMMARY_TEXT_LIMIT:
            text_value = text_value[:_SUMMARY_TEXT_LIMIT]
            truncated = True
        if len(topics) > _SUMMARY_TOPIC_LIMIT:
            topics = topics[:_SUMMARY_TOPIC_LIMIT]
            truncated = True
        topics, topics_truncated = _bound_topic_values(topics)
        truncated = truncated or topics_truncated

    return {"text": text_value, "topics": topics, "truncated": truncated}


def _bound_topic_values(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return value[:_SUMMARY_TOPIC_TEXT_LIMIT], len(value) > _SUMMARY_TOPIC_TEXT_LIMIT
    if isinstance(value, list):
        bounded = [_bound_topic_values(item) for item in value[:_SUMMARY_TOPIC_LIMIT]]
        return [item for item, _ in bounded], len(value) > _SUMMARY_TOPIC_LIMIT or any(
            changed for _, changed in bounded
        )
    if isinstance(value, dict):
        pairs = [(key, _bound_topic_values(item)) for key, item in list(value.items())[:_SUMMARY_TOPIC_LIMIT]]
        bounded = {key: item for key, (item, _) in pairs}
        changed = len(value) > _SUMMARY_TOPIC_LIMIT or any(
            child_changed for _, (_, child_changed) in pairs
        )
        return bounded, changed
    return value, False


def normalize_moment_payload(value: Any, *, summary: bool) -> Any:
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
