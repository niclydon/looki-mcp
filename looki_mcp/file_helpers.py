"""Helpers for Looki FileModel payloads.

As of 2026-07 the Open API nests duration/dimensions under `metadata`
(`{width, height, duration_ms?}`) instead of top-level `duration_ms` / `size`.
Legacy top-level fields are still accepted as a fallback.
"""

from __future__ import annotations

from typing import Any


def file_metadata(file_obj: Any) -> dict[str, Any]:
    """Return the nested metadata dict, or {} if missing/invalid."""
    if not isinstance(file_obj, dict):
        return {}
    meta = file_obj.get("metadata")
    return meta if isinstance(meta, dict) else {}


def file_duration_ms(file_obj: Any) -> int | None:
    """Duration in milliseconds: prefer metadata.duration_ms, then top-level."""
    if not isinstance(file_obj, dict):
        return None
    meta = file_metadata(file_obj)
    for source in (meta.get("duration_ms"), file_obj.get("duration_ms")):
        if source is None:
            continue
        try:
            return int(source)
        except (TypeError, ValueError):
            continue
    return None


def file_dimensions(file_obj: Any) -> tuple[int | None, int | None]:
    """(width, height) from metadata when present."""
    meta = file_metadata(file_obj)
    w, h = meta.get("width"), meta.get("height")
    try:
        width = int(w) if w is not None else None
    except (TypeError, ValueError):
        width = None
    try:
        height = int(h) if h is not None else None
    except (TypeError, ValueError):
        height = None
    return width, height
