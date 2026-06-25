"""Tests for insight.envelope pure serializer. Run: .venv/bin/python scripts/test_envelope.py"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.insight.envelope import render  # noqa: E402

def test_defaults_and_shape():
    out = json.loads(render({"places": []}))
    assert out["data"] == {"places": []}
    assert out["narrative"] is None
    for k, v in {"calls_used":0,"days_scanned":0,"capped":None,"cache_hit":False,"vlm_used":False,"enrichment_skipped_reason":None}.items():
        assert out["meta"][k] == v, (k, out["meta"][k])

def test_meta_merge_and_narrative():
    out = json.loads(render({"x": 1}, narrative="story", meta={"calls_used": 5, "capped": "rate_limit"}))
    assert out["narrative"] == "story"
    assert out["meta"]["calls_used"] == 5 and out["meta"]["capped"] == "rate_limit"
    assert out["meta"]["vlm_used"] is False  # default still present

def main():
    test_defaults_and_shape(); test_meta_merge_and_narrative()
    print("\033[32mPASS\033[0m envelope")

if __name__ == "__main__":
    main()
