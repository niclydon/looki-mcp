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


async def describe_image(image_url: str, prompt: str, *, max_tokens: int = 120) -> str | None:
    return None  # implemented in Task 4/5


async def synthesize(system: str, user: str, *, max_tokens: int = 600) -> str | None:
    return None  # implemented in Task 4/5


async def extract_json(system: str, user: str, *, schema: dict | None = None) -> dict | None:
    return None  # implemented in Task 4/5


async def caption_images(image_urls: list[str], prompt: str, *, concurrency: int = 4) -> list[str | None]:
    return [None for _ in image_urls]  # implemented in Task 6
