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

async def test_openai_compat_describe():
    try:
        _clear()
        os.environ.update({"LOOKI_LLM_PROVIDER":"openai_compatible","LOOKI_LLM_BASE_URL":"http://forge.local","LOOKI_LLM_MODEL":"m","LOOKI_LLM_API_KEY":"sk"})
        seen = {}
        async def fake_post(url, headers, payload, *, timeout=30.0):
            seen["url"] = url; seen["payload"] = payload; seen["auth"] = headers.get("authorization")
            return {"choices": [{"message": {"content": "a dog"}}]}
        llm._http_post = fake_post  # type: ignore
        out = await llm.describe_image("http://x/y.jpg", "what?")
        assert out == "a dog", f"Expected 'a dog', got {out}"
        assert seen["url"].endswith("/v1/chat/completions"), f"URL: {seen['url']}"
        assert seen["auth"] == "Bearer sk", f"Auth: {seen['auth']}"
        # image part present
        content = seen["payload"]["messages"][0]["content"]
        assert any(p.get("type") == "image_url" for p in content), f"No image_url in {content}"
    finally:
        _clear()

def test_anthropic_synthesize():
    try:
        _clear()
        os.environ.update({"LOOKI_LLM_PROVIDER":"anthropic","LOOKI_LLM_API_KEY":"sk","LOOKI_LLM_MODEL":"claude-haiku-4-5"})
        seen = {}
        async def fake_post(url, headers, payload, *, timeout=30.0):
            seen["url"] = url; seen["hdr"] = headers
            return {"content": [{"type": "text", "text": "hi"}]}
        llm._http_post = fake_post  # type: ignore
        out = asyncio.run(llm.synthesize("sys", "user"))
        assert out == "hi"
        assert "/v1/messages" in seen["url"] and seen["hdr"].get("x-api-key") == "sk"
    finally:
        _clear()

def test_gemini_extract_json():
    try:
        _clear()
        os.environ.update({"LOOKI_LLM_PROVIDER":"gemini","LOOKI_LLM_API_KEY":"sk","LOOKI_LLM_MODEL":"gemini-2.5-flash"})
        async def fake_post(url, headers, payload, *, timeout=30.0):
            return {"candidates": [{"content": {"parts": [{"text": "{\"k\": 1}"}]}}]}
        llm._http_post = fake_post  # type: ignore
        out = asyncio.run(llm.extract_json("sys", "user"))
        assert out == {"k": 1}
    finally:
        _clear()

def test_caption_images_order_and_isolation():
    import importlib
    try:
        _clear()
        for k in _KEYS: os.environ.pop(k, None)
        os.environ.update({"LOOKI_LLM_PROVIDER":"openai_compatible","LOOKI_LLM_BASE_URL":"http://f","LOOKI_LLM_MODEL":"m"})
        async def fake_post(url, headers, payload, *, timeout=30.0):
            # echo back the image url tail; raise for the 'bad' one
            img = payload["messages"][0]["content"][1]["image_url"]["url"]
            if img.endswith("bad.jpg"):
                raise RuntimeError("boom")
            return {"choices": [{"message": {"content": img.split("/")[-1]}}]}
        llm._http_post = fake_post  # type: ignore
        out = asyncio.run(llm.caption_images(["http://x/a.jpg","http://x/bad.jpg","http://x/c.jpg"], "p"))
        assert out == ["a.jpg", None, "c.jpg"], out
    finally:
        importlib.reload(llm)
        _clear()

def main():
    test_unconfigured_is_none_and_false()
    test_forge_backcompat()
    test_explicit_provider_wins()
    asyncio.run(test_calls_return_none_when_unconfigured())
    asyncio.run(test_openai_compat_describe())
    import importlib
    importlib.reload(llm)
    _clear()
    test_anthropic_synthesize()
    importlib.reload(llm)
    _clear()
    test_gemini_extract_json()
    importlib.reload(llm)
    _clear()
    test_caption_images_order_and_isolation()
    print("\033[32mPASS\033[0m insight.llm config")

if __name__ == "__main__":
    main()
