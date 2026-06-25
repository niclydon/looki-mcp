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
