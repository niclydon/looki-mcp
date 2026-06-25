"""Tests for insight.llm config resolution + degradation. No network.
Run: .venv/bin/python scripts/test_insight_llm.py
"""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.insight.llm as llm  # noqa: E402

_KEYS = ["LOOKI_LLM_PROVIDER","LOOKI_LLM_BASE_URL","LOOKI_LLM_API_KEY","LOOKI_LLM_MODEL","LOOKI_VLM_MODEL","FORGE_URL","FORGE_API_KEY","FORGE_VLM_MODEL"]
def _clear():
    for k in _KEYS: os.environ.pop(k, None)

def test_unconfigured_is_none_and_false():
    try:
        _clear()
        assert llm.resolve_provider() is None
        assert llm.llm_configured() is False
        assert vlm_false()
    finally:
        _clear()
def vlm_false():
    return llm.vlm_configured() is False

def test_forge_backcompat():
    try:
        _clear()
        os.environ["FORGE_URL"] = "http://forge.local"
        os.environ["FORGE_VLM_MODEL"] = "openai/gpt-4.1-mini"
        cfg = llm.resolve_provider()
        assert cfg and cfg["provider"] == "openai_compatible"
        assert cfg["base_url"] == "http://forge.local"
        assert cfg["vlm_model"] == "openai/gpt-4.1-mini"
    finally:
        _clear()

def test_explicit_provider_wins():
    try:
        _clear()
        os.environ.update({"LOOKI_LLM_PROVIDER":"anthropic","LOOKI_LLM_API_KEY":"sk","LOOKI_LLM_MODEL":"claude-haiku-4-5"})
        cfg = llm.resolve_provider()
        assert cfg["provider"] == "anthropic" and cfg["model"] == "claude-haiku-4-5"
        assert llm.llm_configured() is True
    finally:
        _clear()

async def test_calls_return_none_when_unconfigured():
    try:
        _clear()
        assert await llm.describe_image("http://x/y.jpg", "what?") is None
        assert await llm.synthesize("sys", "user") is None
        assert await llm.caption_images(["a","b"], "p") == [None, None]
    finally:
        _clear()

def main():
    test_unconfigured_is_none_and_false()
    test_forge_backcompat()
    test_explicit_provider_wins()
    asyncio.run(test_calls_return_none_when_unconfigured())
    _clear()
    print("\033[32mPASS\033[0m insight.llm config")

if __name__ == "__main__":
    main()
