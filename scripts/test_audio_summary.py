"""Tests the normalized audio_summary shapes using synthetic, redacted fixtures."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.audio_summary import normalize_audio_summary, normalize_moment_payload  # noqa: E402
from looki_mcp.tools import convenience, moments  # noqa: E402


class _Response:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"code": 0, "detail": "ok", "data": self._data}


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, path, params=None):
        prose = "Synthetic recap."
        structured = json.dumps({"text": "Synthetic detail.", "topics": ["synthetic topic"]})
        if path == "/moments/calendar":
            return _Response([{"date": "2026-11-09", "highlight_moment": {"id": "m1", "audio_summary": prose}}])
        if path == "/moments/search":
            return _Response({"items": [{"id": "m1", "audio_summary": prose}], "has_more": False})
        if path == "/moments/m1/files":
            return _Response({"items": [], "has_more": False})
        if path == "/moments/m1":
            return _Response({"id": "m1", "audio_summary": structured})
        if path == "/moments":
            return _Response([{"id": "m1", "audio_summary": prose}])
        raise AssertionError(f"unexpected request {path}")


class _Mcp:
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def main() -> int:
    prose = "A short synthetic spoken recap."
    assert normalize_audio_summary(prose, summary=False) == {
        "text": prose, "topics": [], "truncated": False,
    }

    structured = json.dumps({
        "text": "Synthetic summary text.",
        "topics": ["synthetic topic", {"label": "synthetic label"}],
    })
    assert normalize_audio_summary(structured, summary=False) == {
        "text": "Synthetic summary text.",
        "topics": ["synthetic topic", {"label": "synthetic label"}],
        "truncated": False,
    }

    long = {"text": "t" * 700, "topics": ["x" * 250] + [f"topic-{i}" for i in range(21)]}
    # Operator rule 2026-11-09: Looki content is never truncated, in any mode.
    compact = normalize_audio_summary(json.dumps(long), summary=True)
    assert compact is not None
    assert len(compact["text"]) == 700
    assert len(compact["topics"]) == 22
    assert len(compact["topics"][0]) == 250
    assert compact["truncated"] is False
    full = normalize_audio_summary(json.dumps(long), summary=False)
    assert full is not None and len(full["text"]) == 700 and len(full["topics"]) == 22
    assert full["truncated"] is False

    payload = {
        "items": [
            {"id": "synthetic-moment", "audio_summary": prose},
            {"id": "structured-moment", "audio_summary": structured},
        ],
        "has_more": False,
    }
    normalized = normalize_moment_payload(payload, summary=True)
    assert normalized["items"][0]["audio_summary"]["text"] == prose
    assert normalized["items"][1]["audio_summary"]["topics"] == [
        "synthetic topic", {"label": "synthetic label"},
    ]
    assert normalize_moment_payload({"audio_summary": None}, summary=True) == {"audio_summary": None}

    client = _Client()
    moments.get_client = lambda: client
    convenience.get_client = lambda: client
    convenience.get_config = lambda: type("Config", (), {"user_timezone": None})()
    mcp = _Mcp()
    moments.register_moments_tools(mcp)
    convenience.register_convenience_tools(mcp)

    by_date = json.loads(asyncio.run(mcp.tools["get_moments_by_date"]("2026-11-09")))
    assert by_date[0]["audio_summary"] == {"text": "Synthetic recap.", "topics": [], "truncated": False}
    search = json.loads(asyncio.run(mcp.tools["search_moments"]("synthetic")))
    assert search["items"][0]["audio_summary"]["text"] == "Synthetic recap."
    detail = json.loads(asyncio.run(mcp.tools["get_moment_details"]("m1")))
    assert detail["audio_summary"]["topics"] == ["synthetic topic"]
    today = json.loads(asyncio.run(mcp.tools["get_todays_moments"]()))
    assert today["data"][0]["audio_summary"]["text"] == "Synthetic recap."
    with_media = json.loads(asyncio.run(mcp.tools["get_moment_with_media"]("m1")))
    assert with_media["moment"]["audio_summary"]["text"] == "Synthetic detail."
    with_details = json.loads(asyncio.run(mcp.tools["search_moments_with_details"]("synthetic")))
    assert with_details["results"][0]["audio_summary"]["topics"] == ["synthetic topic"]
    activity = json.loads(asyncio.run(mcp.tools["get_recent_activity"]()))
    assert activity["data"][0]["highlight_moment"]["audio_summary"]["text"] == "Synthetic recap."
    print("PASS audio_summary normalization (prose, topics JSON, no truncation, nested payload)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
