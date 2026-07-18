"""Location-string normalization + heuristic clustering (zero-LLM).

Looki `location` on cover_file/files is often:
- free-text place names, or
- a JSON **string** of address parts
  (`{"street":"...","locality":"Quincy","administrativeArea":"Massachusetts",...}`)

This groups spellings of the same place by a normalized key (exact-normalized
match — the simplest correct heuristic; fuzzier merging is an optional LLM
upgrade, deferred). Null/empty locations are counted separately as `unknown`.
"""
from __future__ import annotations

import json
import re
from collections import Counter

_WS_RE = re.compile(r"\s+")


def _display_from_address_obj(obj: dict) -> str | None:
    """Build a human-readable place label from a parsed address dict."""
    locality = obj.get("locality")
    admin = obj.get("administrativeArea")
    street = obj.get("street")
    country = obj.get("isoCountryCode")
    parts: list[str] = []
    for part in (locality, admin, country):
        if isinstance(part, str) and part.strip():
            parts.append(part.strip())
    if parts:
        return ", ".join(parts)
    if isinstance(street, str) and street.strip():
        return street.strip()
    return None


def parse_location_display(value) -> str | None:
    """Return a human-readable location string, or None if empty/unusable.

    JSON address blobs are collapsed to locality (+ admin/country) so clustering
    does not key on the full serialized JSON.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            display = _display_from_address_obj(obj)
            if display:
                return display
            # Malformed/empty object → fall through to raw strip
    return s


def normalize_location(value) -> str | None:
    """Normalized cluster key (lowercased display text), or None if unknown."""
    display = parse_location_display(value)
    if display is None:
        return None
    s = _WS_RE.sub(" ", display.strip()).strip(" .,;:-")
    return s.lower() or None


def cluster_locations(values: list) -> dict:
    # key -> list of original/display spellings (only non-null)
    groups: dict[str, list[str]] = {}
    unknown = 0
    for v in values:
        key = normalize_location(v)
        if key is None:
            unknown += 1
            continue
        display = parse_location_display(v) or (v.strip() if isinstance(v, str) else key)
        groups.setdefault(key, []).append(display)
    places = []
    for key, spellings in groups.items():
        name = Counter(spellings).most_common(1)[0][0]
        places.append({"name": name, "key": key, "count": len(spellings)})
    places.sort(key=lambda p: p["count"], reverse=True)
    return {"places": places, "unknown_count": unknown}
