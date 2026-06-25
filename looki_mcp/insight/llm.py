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


async def _provider_image(cfg: dict, prompt: str, image_url: str, max_tokens: int) -> str | None:
    """Placeholder for Task 5 (anthropic, gemini providers)."""
    raise NotImplementedError(f"Image description not yet implemented for provider '{cfg['provider']}'")


async def _provider_text(cfg: dict, system: str, user: str, max_tokens: int) -> str | None:
    """Placeholder for Task 5 (anthropic, gemini providers)."""
    raise NotImplementedError(f"Text synthesis not yet implemented for provider '{cfg['provider']}'")


async def _provider_json(cfg: dict, system: str, user: str, schema: dict | None) -> str | None:
    """Placeholder for Task 5 (anthropic, gemini providers)."""
    raise NotImplementedError(f"JSON extraction not yet implemented for provider '{cfg['provider']}'")


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
    return [None for _ in image_urls]  # implemented in Task 6
