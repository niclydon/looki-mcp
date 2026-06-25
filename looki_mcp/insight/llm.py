"""Provider-agnostic LLM/VLM layer. Generalizes tools/realtime.py's Forge call.

Configured entirely via env (the optional-feature convention). When no provider
is configured, every call is a graceful no-op returning None / [..None] and NEVER
raises into a tool. NEVER logs LOOKI_LLM_API_KEY.
"""
from __future__ import annotations
import asyncio
import os
from typing import Any

import httpx

_VALID = {"openai", "anthropic", "gemini", "openai_compatible"}


def resolve_provider() -> dict | None:
    provider = os.environ.get("LOOKI_LLM_PROVIDER", "").strip().lower()
    base_url = os.environ.get("LOOKI_LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LOOKI_LLM_API_KEY", "").strip()
    model = os.environ.get("LOOKI_LLM_MODEL", "").strip()
    vlm_model = os.environ.get("LOOKI_VLM_MODEL", "").strip() or model

    if not provider or provider == "none":
        # Back-compat: a Forge URL alone enables openai_compatible.
        forge = os.environ.get("FORGE_URL", "").strip()
        if forge:
            return {
                "provider": "openai_compatible",
                "base_url": forge,
                "api_key": os.environ.get("FORGE_API_KEY", "").strip(),
                "model": os.environ.get("FORGE_VLM_MODEL", "openai/gpt-4.1-mini").strip(),
                "vlm_model": os.environ.get("FORGE_VLM_MODEL", "openai/gpt-4.1-mini").strip(),
            }
        return None
    if provider not in _VALID:
        return None
    return {"provider": provider, "base_url": base_url, "api_key": api_key, "model": model, "vlm_model": vlm_model}


def llm_configured() -> bool:
    return resolve_provider() is not None


def vlm_configured() -> bool:
    cfg = resolve_provider()
    return bool(cfg and cfg.get("vlm_model"))


async def _http_post(url: str, headers: dict, payload: dict, *, timeout: float = 30.0) -> dict:
    """The single network seam — monkeypatched in unit tests."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


async def _openai_chat(cfg: dict, messages: list, *, max_tokens: int, json_mode: bool = False) -> str | None:
    headers = {"content-type": "application/json"}
    if cfg["api_key"]:
        headers["authorization"] = f"Bearer {cfg['api_key']}"
    payload: dict = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    base = cfg["base_url"].rstrip("/") if cfg["base_url"] else "https://api.openai.com"
    data = await _http_post(f"{base}/v1/chat/completions", headers, payload)
    return data.get("choices", [{}])[0].get("message", {}).get("content")


def _anthropic_headers(cfg: dict) -> dict:
    return {"content-type": "application/json", "x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"}


async def _anthropic_messages(cfg: dict, system: str, content, *, max_tokens: int) -> str | None:
    base = (cfg["base_url"] or "https://api.anthropic.com").rstrip("/")
    payload = {"model": cfg["model"], "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": content}]}
    data = await _http_post(f"{base}/v1/messages", _anthropic_headers(cfg), payload)
    parts = data.get("content", [])
    return parts[0].get("text") if parts else None


def _anthropic_image_source(url: str) -> dict:
    # Expects a data: URL (base64). PR3's VLM tools download bytes first (spec M4).
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        media_type = header.split(";")[0].removeprefix("data:") or "image/jpeg"
        return {"type": "base64", "media_type": media_type, "data": b64}
    return {"type": "url", "url": url}


def _gemini_image_part(url: str) -> dict:
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        return {"inline_data": {"mime_type": header.split(";")[0].removeprefix("data:"), "data": b64}}
    return {"file_data": {"file_uri": url}}


async def _gemini_generate(cfg: dict, system: str, parts: list, *, max_tokens: int, force_json: bool = False) -> str | None:
    base = (cfg["base_url"] or "https://generativelanguage.googleapis.com").rstrip("/")
    url = f"{base}/v1beta/models/{cfg['model']}:generateContent?key={cfg['api_key']}"
    payload: dict = {"contents": [{"parts": parts}], "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if force_json:
        # Gemini's reliable structured-output knob is responseMimeType; its OpenAI-compat
        # json_schema support is partial, so we ask for JSON and parse in extract_json.
        payload["generationConfig"]["responseMimeType"] = "application/json"
    data = await _http_post(url, {"content-type": "application/json"}, payload)
    cands = data.get("candidates", [])
    if not cands:
        return None
    gparts = cands[0].get("content", {}).get("parts", [])
    return gparts[0].get("text") if gparts else None


async def _provider_image(cfg: dict, prompt: str, image_url: str, max_tokens: int) -> str | None:
    """Task 5: anthropic, gemini providers."""
    if cfg["provider"] == "anthropic":
        # Anthropic needs base64 image source, not a URL — caller passes a data: URL (Task 6/PR3).
        content = [{"type": "text", "text": prompt}, {"type": "image", "source": _anthropic_image_source(image_url)}]
        return await _anthropic_messages({**cfg, "model": cfg["vlm_model"]}, "", content, max_tokens=max_tokens)
    return await _gemini_generate({**cfg, "model": cfg["vlm_model"]}, "", [{"text": prompt}, _gemini_image_part(image_url)], max_tokens=max_tokens)


async def _provider_text(cfg: dict, system: str, user: str, max_tokens: int) -> str | None:
    """Task 5: anthropic, gemini providers."""
    if cfg["provider"] == "anthropic":
        return await _anthropic_messages(cfg, system, [{"type": "text", "text": user}], max_tokens=max_tokens)
    return await _gemini_generate(cfg, system, [{"text": user}], max_tokens=max_tokens)


async def _provider_json(cfg: dict, system: str, user: str, schema: dict | None) -> str | None:
    """Task 5: anthropic, gemini providers."""
    if cfg["provider"] == "anthropic":
        return await _anthropic_messages(cfg, system + " Respond with ONLY valid JSON.", [{"type": "text", "text": user}], max_tokens=900)
    return await _gemini_generate(cfg, system, [{"text": user}], max_tokens=900, force_json=True)


async def describe_image(image_url: str, prompt: str, *, max_tokens: int = 120) -> str | None:
    cfg = resolve_provider()
    if cfg is None:
        return None
    try:
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]}]
        if cfg["provider"] in ("openai", "openai_compatible"):
            return await _openai_chat({**cfg, "model": cfg["vlm_model"]}, messages, max_tokens=max_tokens)
        return await _provider_image(cfg, prompt, image_url, max_tokens)  # Task 5
    except Exception:
        return None


async def synthesize(system: str, user: str, *, max_tokens: int = 600) -> str | None:
    cfg = resolve_provider()
    if cfg is None:
        return None
    try:
        if cfg["provider"] in ("openai", "openai_compatible"):
            return await _openai_chat(cfg, [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens)
        return await _provider_text(cfg, system, user, max_tokens)  # Task 5
    except Exception:
        return None


async def extract_json(system: str, user: str, *, schema: dict | None = None) -> dict | None:
    cfg = resolve_provider()
    if cfg is None:
        return None
    try:
        if cfg["provider"] in ("openai", "openai_compatible"):
            text = await _openai_chat(cfg, [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=900, json_mode=True)
        else:
            text = await _provider_json(cfg, system, user, schema)  # Task 5
        import json as _json
        return _json.loads(text) if text else None
    except Exception:
        return None


async def caption_images(image_urls: list[str], prompt: str, *, concurrency: int = 4) -> list[str | None]:
    if not llm_configured():
        return [None for _ in image_urls]
    sem = asyncio.Semaphore(max(1, concurrency))
    async def _one(u: str) -> str | None:
        async with sem:
            return await describe_image(u, prompt)
    return list(await asyncio.gather(*[_one(u) for u in image_urls]))
