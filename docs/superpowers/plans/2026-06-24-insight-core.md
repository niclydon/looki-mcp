# Insight Core (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared "Insight Core" library that the 10 magic composite tools (PR2/PR3) depend on — provider-agnostic LLM/VLM, a rate-limit throughput governor, per-shape API scanners, a pure output envelope, durable-capture + cache helpers — and refactor the one existing VLM tool onto it.

**Architecture:** A new `looki_mcp/insight/` package of small, single-responsibility modules. Optional integrations (LLM/VLM, MinIO) follow the repo's established pattern: read `os.environ` directly, cache a singleton behind a `False` "not-built" sentinel, and **degrade to a graceful no-op (return `None`) when unconfigured — never raise into a tool.** No new heavyweight SDK deps; HTTP via `httpx` (the pattern in `tools/realtime.py`).

**Tech Stack:** Python 3.11+, `fastmcp`, `httpx` (async), `boto3` (already used by `storage.py`, sync calls offloaded with `asyncio.to_thread`). Tests are **standalone scripts** run with `.venv/bin/python scripts/test_*.py` (this repo does NOT use pytest — match `scripts/test_journals_helpers.py`).

## Global Constraints

- **Public repo, no private-homelab hard deps.** Forge / MinIO / any LLM provider are all optional; absence is a no-op, never an error.
- **Provider-agnostic LLM/VLM.** Env `LOOKI_LLM_PROVIDER` ∈ `none|openai|anthropic|gemini|openai_compatible` (default `none`). Forge = an `openai_compatible` base URL. Back-compat: `FORGE_URL` set + provider unset ⇒ auto `openai_compatible` from `FORGE_URL`/`FORGE_API_KEY`/`FORGE_VLM_MODEL`.
- **Graceful degradation contract:** `llm_configured()`/`vlm_configured()` return `False` when unconfigured; all async LLM calls return `None` (or `[…None]`) on unconfigured-or-error and **never raise**.
- **60 req/min Looki limit** is enforced by a throughput **governor**, not a call counter. All insight Looki + VLM calls route through it. `client.py` honors HTTP 429 `Retry-After`.
- **Secrets/trace hygiene:** never log `LOOKI_LLM_API_KEY`; Langfuse (when enabled) logs metadata (lengths/counts) only — never image bytes or journal/OCR content.
- **No new runtime dependencies** beyond what's already in `requirements.txt` (`httpx`, `boto3`, `fastmcp`, `python-dotenv`).
- **Determinism in tests:** inject clocks/transports; never sleep on the wall clock or hit the network in `scripts/test_*.py`.

**Spec:** `docs/superpowers/specs/2026-06-24-looki-magic-composite-tools-design.md` (v2).

---

### Task 1: `insight/governor.py` — throughput governor

**Files:**
- Create: `looki_mcp/insight/__init__.py` (empty)
- Create: `looki_mcp/insight/governor.py`
- Test: `scripts/test_governor.py`

**Interfaces:**
- Produces: `class RateGovernor(rate_per_min: float = 50.0, *, now: Callable[[], float] = time.monotonic)` with `async def slot(self) -> AsyncContextManager`, and `def _take(self, n: int = 1) -> float` (returns seconds-to-wait, 0 if a token is free now). Module singleton `get_governor() -> RateGovernor`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test** — token-bucket math with an injected clock (no real sleep).

```python
# scripts/test_governor.py
"""Unit tests for the insight rate governor (injected clock, no real sleep).
Run: .venv/bin/python scripts/test_governor.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.insight.governor import RateGovernor  # noqa: E402

def test_first_calls_are_free_then_throttle():
    t = [0.0]
    g = RateGovernor(rate_per_min=60.0, now=lambda: t[0])  # 1 token/sec, burst=capacity
    # Drain the full burst capacity (capacity == rate by default) with no wait.
    waits = [g._take() for _ in range(60)]
    assert all(w == 0 for w in waits), f"burst should be free, got {waits[:5]}"
    # 61st call in the same instant must wait ~1s for the next token.
    w = g._take()
    assert 0.9 <= w <= 1.1, f"expected ~1s wait, got {w}"

def test_tokens_refill_over_time():
    t = [0.0]
    g = RateGovernor(rate_per_min=60.0, now=lambda: t[0])
    for _ in range(60):
        g._take()
    t[0] = 5.0  # 5 seconds later -> ~5 tokens refilled
    waits = [g._take() for _ in range(5)]
    assert all(w == 0 for w in waits), f"refilled tokens should be free, got {waits}"
    assert g._take() > 0, "6th after 5s refill should throttle"

def main():
    test_first_calls_are_free_then_throttle()
    test_tokens_refill_over_time()
    print("\033[32mPASS\033[0m governor")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_governor.py`
Expected: `ModuleNotFoundError: looki_mcp.insight.governor`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/insight/governor.py
"""Shared async throughput governor for Looki + VLM calls.

The Looki API enforces 60 req/min as a sliding window (HTTP 429). A call-COUNT
budget cannot prevent that; this token-bucket bounds THROUGHPUT. One process-wide
singleton is shared by every insight tool so concurrent fan-outs (e.g. captioning
N photos) cannot collectively exceed the window.

`now` is injectable so the bucket math is unit-testable without sleeping.
"""
from __future__ import annotations
import asyncio
import time
from contextlib import asynccontextmanager
from typing import Callable


class RateGovernor:
    def __init__(self, rate_per_min: float = 50.0, *, now: Callable[[], float] = time.monotonic) -> None:
        self._rate_per_sec = rate_per_min / 60.0
        self._capacity = rate_per_min          # allow one minute's burst
        self._tokens = float(rate_per_min)
        self._now = now
        self._last = now()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        t = self._now()
        elapsed = max(0.0, t - self._last)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)
        self._last = t

    def _take(self, n: int = 1) -> float:
        """Consume n tokens. Returns seconds to wait before they're available (0 if free now)."""
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return 0.0
        deficit = n - self._tokens
        self._tokens = 0.0
        return deficit / self._rate_per_sec

    @asynccontextmanager
    async def slot(self):
        async with self._lock:
            wait = self._take()
        if wait > 0:
            await asyncio.sleep(wait)
        yield


_governor: RateGovernor | None = None


def get_governor() -> RateGovernor:
    global _governor
    if _governor is None:
        _governor = RateGovernor()
    return _governor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_governor.py`
Expected: `PASS governor`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/__init__.py looki_mcp/insight/governor.py scripts/test_governor.py
git commit -m "feat(insight): add token-bucket rate governor"
```

---

### Task 2: `client.py` — 429 backoff + governed GET helper

**Files:**
- Modify: `looki_mcp/client.py` (add `governed_get`, leave `get_client`/`unwrap`/`format_error` intact)
- Test: `scripts/test_governed_get.py`

**Interfaces:**
- Consumes: `RateGovernor` (Task 1), `get_client()` (existing).
- Produces: `async def governed_get(client: httpx.AsyncClient, url: str, *, params: dict | None = None, max_retries: int = 2) -> httpx.Response` — routes through the governor, and on HTTP 429 sleeps `Retry-After` (capped) and retries up to `max_retries`, re-raising `httpx.HTTPStatusError` if still 429.

- [ ] **Step 1: Write the failing test** — drive it with `httpx.MockTransport`; patch governor sleep + `Retry-After` sleep to no-op so the test is instant.

```python
# scripts/test_governed_get.py
"""Tests for client.governed_get: 429 Retry-After backoff. No real network/sleep.
Run: .venv/bin/python scripts/test_governed_get.py
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import looki_mcp.client as client_mod  # noqa: E402

async def _run(handler):
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as c:
        return await client_mod.governed_get(c, "/moments", params={"on_date": "2026-06-01"})

def test_retries_then_succeeds(monkeypatch_sleep):
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"code": 429, "detail": "rate"})
        return httpx.Response(200, json={"code": 0, "detail": "ok", "data": []})
    resp = asyncio.run(_run(handler))
    assert resp.status_code == 200 and calls["n"] == 2

def main():
    # Patch BOTH sleeps (governor + backoff) to no-op for an instant test.
    import looki_mcp.insight.governor as gov
    async def _nosleep(*a, **k): return None
    orig = asyncio.sleep
    asyncio.sleep = _nosleep  # type: ignore
    try:
        test_retries_then_succeeds(None)
    finally:
        asyncio.sleep = orig  # type: ignore
    print("\033[32mPASS\033[0m governed_get")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_governed_get.py`
Expected: `AttributeError: module 'looki_mcp.client' has no attribute 'governed_get'`.

- [ ] **Step 3: Write minimal implementation** — append to `looki_mcp/client.py`:

```python
# --- appended to looki_mcp/client.py ---
import asyncio

from looki_mcp.insight.governor import get_governor

_MAX_RETRY_AFTER_SECONDS = 30.0


async def governed_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 2,
) -> httpx.Response:
    """GET routed through the shared rate governor, with 429 Retry-After backoff.

    Raises httpx.HTTPStatusError if still 429 after max_retries (callers map it
    via format_error). Non-429 4xx/5xx raise immediately via raise_for_status().
    """
    governor = get_governor()
    attempt = 0
    while True:
        async with governor.slot():
            response = await client.get(url, params=params)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt >= max_retries:
            response.raise_for_status()  # raises HTTPStatusError(429)
        retry_after = response.headers.get("retry-after")
        try:
            delay = min(float(retry_after), _MAX_RETRY_AFTER_SECONDS) if retry_after else 1.0
        except ValueError:
            delay = 1.0
        await asyncio.sleep(delay)
        attempt += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_governed_get.py`
Expected: `PASS governed_get`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/client.py scripts/test_governed_get.py
git commit -m "feat(client): governed GET with 429 Retry-After backoff"
```

---

### Task 3: `insight/llm.py` — config resolution + degradation contract

**Files:**
- Create: `looki_mcp/insight/llm.py`
- Test: `scripts/test_insight_llm.py`

**Interfaces:**
- Produces: `def resolve_provider() -> dict | None` (returns `{provider, base_url, api_key, model, vlm_model}` or `None` when unconfigured, applying `FORGE_*` back-compat); `def llm_configured() -> bool`; `def vlm_configured() -> bool`; `async def _http_post(url, headers, payload, *, timeout=30.0) -> dict` (the single network seam tests monkeypatch).
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_insight_llm.py
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
    _clear()
    assert llm.resolve_provider() is None
    assert llm.llm_configured() is False
    assert vlm_false()
def vlm_false():
    return llm.vlm_configured() is False

def test_forge_backcompat():
    _clear()
    os.environ["FORGE_URL"] = "http://forge.local"
    os.environ["FORGE_VLM_MODEL"] = "openai/gpt-4.1-mini"
    cfg = llm.resolve_provider()
    assert cfg and cfg["provider"] == "openai_compatible"
    assert cfg["base_url"] == "http://forge.local"
    assert cfg["vlm_model"] == "openai/gpt-4.1-mini"

def test_explicit_provider_wins():
    _clear()
    os.environ.update({"LOOKI_LLM_PROVIDER":"anthropic","LOOKI_LLM_API_KEY":"sk","LOOKI_LLM_MODEL":"claude-haiku-4-5"})
    cfg = llm.resolve_provider()
    assert cfg["provider"] == "anthropic" and cfg["model"] == "claude-haiku-4-5"
    assert llm.llm_configured() is True

async def test_calls_return_none_when_unconfigured():
    _clear()
    assert await llm.describe_image("http://x/y.jpg", "what?") is None
    assert await llm.synthesize("sys", "user") is None
    assert await llm.caption_images(["a","b"], "p") == [None, None]

def main():
    test_unconfigured_is_none_and_false()
    test_forge_backcompat()
    test_explicit_provider_wins()
    asyncio.run(test_calls_return_none_when_unconfigured())
    _clear()
    print("\033[32mPASS\033[0m insight.llm config")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: `ModuleNotFoundError: looki_mcp.insight.llm`.

- [ ] **Step 3: Write minimal implementation** (config + stubs that the next tasks flesh out; degradation already correct):

```python
# looki_mcp/insight/llm.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: `PASS insight.llm config`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/llm.py scripts/test_insight_llm.py
git commit -m "feat(insight): llm provider resolution + degradation contract"
```

---

### Task 4: `insight/llm.py` — OpenAI-compatible adapter (describe/synthesize/extract)

**Files:**
- Modify: `looki_mcp/insight/llm.py`
- Test: extend `scripts/test_insight_llm.py`

**Interfaces:**
- Produces: working `describe_image`/`synthesize`/`extract_json` for `provider ∈ {openai, openai_compatible}` via OpenAI `/v1/chat/completions`; all wrap `_http_post` in try/except → `None` on any error.
- Consumes: `resolve_provider`, `_http_post`.

- [ ] **Step 1: Write the failing test** — monkeypatch `_http_post`, assert payload shape + parsing.

```python
# append to scripts/test_insight_llm.py
def test_openai_compat_describe(monkey=None):
    import os
    for k in _KEYS: os.environ.pop(k, None)
    os.environ.update({"LOOKI_LLM_PROVIDER":"openai_compatible","LOOKI_LLM_BASE_URL":"http://forge.local","LOOKI_LLM_MODEL":"m","LOOKI_LLM_API_KEY":"sk"})
    seen = {}
    async def fake_post(url, headers, payload, *, timeout=30.0):
        seen["url"] = url; seen["payload"] = payload; seen["auth"] = headers.get("authorization")
        return {"choices": [{"message": {"content": "a dog"}}]}
    llm._http_post = fake_post  # type: ignore
    out = asyncio.run(llm.describe_image("http://x/y.jpg", "what?"))
    assert out == "a dog"
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer sk"
    # image part present
    content = seen["payload"]["messages"][0]["content"]
    assert any(p.get("type") == "image_url" for p in content)
```

Add `test_openai_compat_describe()` to `main()` (before the final `_clear()`), and after it restore the real `_http_post` by re-importing: `import importlib; importlib.reload(llm)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: FAIL — `describe_image` returns `None`.

- [ ] **Step 3: Write minimal implementation** — replace the three stub bodies:

```python
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
```

Add placeholder `async def _provider_image/_provider_text/_provider_json` raising `NotImplementedError` for now (Task 5 fills them); the try/except keeps non-openai providers degrading to `None` until then.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: `PASS insight.llm config`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/llm.py scripts/test_insight_llm.py
git commit -m "feat(insight): OpenAI-compatible LLM/VLM adapter"
```

---

### Task 5: `insight/llm.py` — Anthropic + Gemini adapters

**Files:**
- Modify: `looki_mcp/insight/llm.py`
- Test: extend `scripts/test_insight_llm.py`

**Interfaces:**
- Produces: `_provider_text`, `_provider_image`, `_provider_json` implemented for `anthropic` (Messages API) and `gemini` (its `generateContent` with `response_mime_type`/`response_schema` for JSON and `inline`/`fileData` image parts).
- Consumes: `_http_post`.

- [ ] **Step 1: Write the failing test** — one Anthropic synth + one Gemini extract_json, monkeypatching `_http_post`.

```python
# append to scripts/test_insight_llm.py
def test_anthropic_synthesize():
    import os
    for k in _KEYS: os.environ.pop(k, None)
    os.environ.update({"LOOKI_LLM_PROVIDER":"anthropic","LOOKI_LLM_API_KEY":"sk","LOOKI_LLM_MODEL":"claude-haiku-4-5"})
    seen = {}
    async def fake_post(url, headers, payload, *, timeout=30.0):
        seen["url"] = url; seen["hdr"] = headers
        return {"content": [{"type": "text", "text": "hi"}]}
    llm._http_post = fake_post  # type: ignore
    out = asyncio.run(llm.synthesize("sys", "user"))
    assert out == "hi"
    assert "/v1/messages" in seen["url"] and seen["hdr"].get("x-api-key") == "sk"

def test_gemini_extract_json():
    import os
    for k in _KEYS: os.environ.pop(k, None)
    os.environ.update({"LOOKI_LLM_PROVIDER":"gemini","LOOKI_LLM_API_KEY":"sk","LOOKI_LLM_MODEL":"gemini-2.5-flash"})
    async def fake_post(url, headers, payload, *, timeout=30.0):
        return {"candidates": [{"content": {"parts": [{"text": "{\"k\": 1}"}]}}]}
    llm._http_post = fake_post  # type: ignore
    out = asyncio.run(llm.extract_json("sys", "user"))
    assert out == {"k": 1}
```

Add both to `main()`; reload `llm` afterward.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: FAIL — `NotImplementedError` swallowed → `None`, assertion fails.

- [ ] **Step 3: Write minimal implementation** — replace the three `_provider_*` placeholders:

```python
def _anthropic_headers(cfg: dict) -> dict:
    return {"content-type": "application/json", "x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"}

async def _anthropic_messages(cfg: dict, system: str, content, *, max_tokens: int) -> str | None:
    base = (cfg["base_url"] or "https://api.anthropic.com").rstrip("/")
    payload = {"model": cfg["model"], "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": content}]}
    data = await _http_post(f"{base}/v1/messages", _anthropic_headers(cfg), payload)
    parts = data.get("content", [])
    return parts[0].get("text") if parts else None

async def _provider_text(cfg, system, user, max_tokens):
    if cfg["provider"] == "anthropic":
        return await _anthropic_messages(cfg, system, [{"type": "text", "text": user}], max_tokens=max_tokens)
    return await _gemini_generate(cfg, system, [{"text": user}], max_tokens=max_tokens)

async def _provider_image(cfg, prompt, image_url, max_tokens):
    if cfg["provider"] == "anthropic":
        # Anthropic needs base64 image source, not a URL — caller passes a data: URL (Task 6/PR3).
        content = [{"type": "text", "text": prompt}, {"type": "image", "source": _anthropic_image_source(image_url)}]
        return await _anthropic_messages({**cfg, "model": cfg["vlm_model"]}, "", content, max_tokens=max_tokens)
    return await _gemini_generate({**cfg, "model": cfg["vlm_model"]}, "", [{"text": prompt}, _gemini_image_part(image_url)], max_tokens=max_tokens)

async def _provider_json(cfg, system, user, schema):
    if cfg["provider"] == "anthropic":
        return await _anthropic_messages(cfg, system + " Respond with ONLY valid JSON.", [{"type": "text", "text": user}], max_tokens=900)
    return await _gemini_generate(cfg, system, [{"text": user}], max_tokens=900, force_json=True)

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
```

Note: `extract_json` parses the returned text with `json.loads` (Task 4) regardless of provider; the Gemini path sets `responseMimeType=application/json` via `force_json=True` so the model returns parseable JSON. The `schema` arg to `extract_json` is advisory (used in the system prompt), not sent as a provider `responseSchema`, since cross-provider schema support is uneven.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: `PASS insight.llm config`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/llm.py scripts/test_insight_llm.py
git commit -m "feat(insight): Anthropic + Gemini LLM/VLM adapters"
```

---

### Task 6: `insight/llm.py` — `caption_images` with governed concurrency

**Files:**
- Modify: `looki_mcp/insight/llm.py`
- Test: extend `scripts/test_insight_llm.py`

**Interfaces:**
- Produces: `caption_images(urls, prompt, concurrency=4)` runs `describe_image` per URL under an `asyncio.Semaphore(concurrency)`, each acquiring a governor slot (via `describe_image`'s path), returning per-URL `str|None` preserving order; failures isolated to `None`.

- [ ] **Step 1: Write the failing test**

```python
# append to scripts/test_insight_llm.py
def test_caption_images_order_and_isolation():
    import os
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: FAIL — stub returns `[None, None, None]`.

- [ ] **Step 3: Write minimal implementation** — replace `caption_images`:

```python
async def caption_images(image_urls: list[str], prompt: str, *, concurrency: int = 4) -> list[str | None]:
    if not llm_configured():
        return [None for _ in image_urls]
    sem = asyncio.Semaphore(max(1, concurrency))
    async def _one(u: str) -> str | None:
        async with sem:
            return await describe_image(u, prompt)
    return list(await asyncio.gather(*[_one(u) for u in image_urls]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_insight_llm.py`
Expected: `PASS insight.llm config`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/llm.py scripts/test_insight_llm.py
git commit -m "feat(insight): caption_images with bounded concurrency"
```

---

### Task 7: `insight/envelope.py` — pure output serializer

**Files:**
- Create: `looki_mcp/insight/envelope.py`
- Test: `scripts/test_envelope.py`

**Interfaces:**
- Produces: `def render(data, *, narrative: str | None = None, meta: dict | None = None) -> str` — returns `json.dumps({"data":..., "narrative":..., "meta": <uniform>}, indent=2)`. `meta` is normalized to always include keys `calls_used, days_scanned, capped, cache_hit, vlm_used, enrichment_skipped_reason` (defaults `0,0,None,False,False,None`). **Does NOT call llm.py.**

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_envelope.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_envelope.py`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/insight/envelope.py
"""Pure serializer for the {data, narrative, meta} hybrid-output contract.

Intentionally does NOT call the LLM layer — tools synthesize narrative themselves
(via insight.llm.synthesize) and pass the string in. This keeps the LLM dependency
out of every tool's output path and makes the envelope trivially testable.
"""
from __future__ import annotations
import json
from typing import Any

_META_DEFAULTS = {
    "calls_used": 0,
    "days_scanned": 0,
    "capped": None,          # None | "budget" | "rate_limit"
    "cache_hit": False,
    "vlm_used": False,
    "enrichment_skipped_reason": None,
}


def render(data: Any, *, narrative: str | None = None, meta: dict | None = None) -> str:
    merged = {**_META_DEFAULTS, **(meta or {})}
    return json.dumps({"data": data, "narrative": narrative, "meta": merged}, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_envelope.py`
Expected: `PASS envelope`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/envelope.py scripts/test_envelope.py
git commit -m "feat(insight): pure {data,narrative,meta} envelope serializer"
```

---

### Task 8: `storage.py` — generic `media_key` (non-journal namespaces)

**Files:**
- Modify: `looki_mcp/storage.py` (add `media_key_for`; keep existing `media_key` untouched)
- Test: `scripts/test_storage_media_key.py`

**Interfaces:**
- Produces: `def media_key_for(prefix: str, owner_id: str, date: str | None, idx: int, kind: str, url: str) -> str` → `"<prefix>/<date|undated>/<owner_id>/<idx>_<kind><ext>"`, reusing the existing `_ext_from_url`.
- Consumes: existing `_ext_from_url`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_storage_media_key.py
"""Tests for storage.media_key_for. Run: .venv/bin/python scripts/test_storage_media_key.py"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looki_mcp.storage import media_key_for, media_key  # noqa: E402

def test_moment_namespace():
    k = media_key_for("moments", "M123", "2026-06-20", 0, "hero", "http://x/p.png?t=1")
    assert k == "moments/2026-06-20/M123/0_hero.png", k

def test_undated_and_default_ext():
    k = media_key_for("insight", "Y1", None, 2, "source", "http://x/noext")
    assert k == "insight/undated/Y1/2_source.jpg", k

def test_journal_key_unchanged():
    assert media_key("J1", "2026-06-20", 0, "source", "http://x/a.jpg").startswith("journals/2026-06-20/J1/")

def main():
    test_moment_namespace(); test_undated_and_default_ext(); test_journal_key_unchanged()
    print("\033[32mPASS\033[0m storage.media_key_for")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_storage_media_key.py`
Expected: `ImportError: cannot import name 'media_key_for'`.

- [ ] **Step 3: Write minimal implementation** — add to `looki_mcp/storage.py` near `media_key`:

```python
def media_key_for(prefix: str, owner_id: str, date: str | None, idx: int, kind: str, url: str) -> str:
    """Generic, idempotent object key for any namespace (moments, for_you, insight).

    Mirrors media_key() but parameterizes the top-level prefix + owner id so moment
    and for_you hero images don't collide with the journals/ tree.
    """
    safe_date = date or "undated"
    return f"{prefix}/{safe_date}/{owner_id}/{idx}_{kind}{_ext_from_url(url)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_storage_media_key.py`
Expected: `PASS storage.media_key_for`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/storage.py scripts/test_storage_media_key.py
git commit -m "feat(storage): generic media_key_for non-journal namespaces"
```

---

### Task 9: `insight/cache.py` — resolved-window memo cache

**Files:**
- Create: `looki_mcp/insight/cache.py`
- Test: `scripts/test_cache.py`

**Interfaces:**
- Produces: `def window_key(tool: str, *, today_local: str, **params) -> str` (stable key embedding the RESOLVED window, never a relative arg alone); `async def cache_get(key, *, ttl_seconds) -> dict | None`; `async def cache_put(key, value: dict) -> None`. In-process dict singleton always works; MinIO/object-store layer used additively when configured (reuse `storage.get_client`). TTL honored in-process via a stored `_built_at` (injected clock for tests).
- Consumes: `storage` (optional).

- [ ] **Step 1: Write the failing test** (in-process layer only; injected clock):

```python
# scripts/test_cache.py
"""Tests for insight.cache in-process layer + window keys. Run: .venv/bin/python scripts/test_cache.py"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.insight.cache as cache  # noqa: E402

def test_window_key_includes_resolved_window():
    k1 = cache.window_key("places_of_my_life", today_local="2026-06-24", days=30)
    k2 = cache.window_key("places_of_my_life", today_local="2026-07-10", days=30)
    assert k1 != k2, "same days arg on different days must yield different keys"

def test_put_get_and_ttl():
    t = [100.0]
    cache._now = lambda: t[0]  # type: ignore
    cache._MEM.clear()
    asyncio.run(cache.cache_put("k", {"v": 1}))
    assert asyncio.run(cache.cache_get("k", ttl_seconds=60)) == {"v": 1}
    t[0] = 100.0 + 61
    assert asyncio.run(cache.cache_get("k", ttl_seconds=60)) is None  # expired

def main():
    test_window_key_includes_resolved_window(); test_put_get_and_ttl()
    print("\033[32mPASS\033[0m insight.cache")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_cache.py`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/insight/cache.py
"""Process-lifetime memo cache for deep insight tools, keyed on the RESOLVED window.

Keying on a relative arg (days=30) would serve a stale window tomorrow, so keys
embed today_local + params. In-process dict is the always-on layer (survives across
tool calls within one server process); an object-store layer is added when MinIO is
configured (reuse storage.py). `_now` is injectable for TTL tests.
"""
from __future__ import annotations
import time
from typing import Any

_MEM: dict[str, dict] = {}
_now = time.time


def window_key(tool: str, *, today_local: str, **params) -> str:
    parts = [tool, f"today={today_local}"] + [f"{k}={params[k]}" for k in sorted(params)]
    return "|".join(parts)


async def cache_get(key: str, *, ttl_seconds: float) -> Any | None:
    entry = _MEM.get(key)
    if entry is None:
        return None
    if _now() - entry["_built_at"] > ttl_seconds:
        _MEM.pop(key, None)
        return None
    return entry["value"]


async def cache_put(key: str, value: Any) -> None:
    _MEM[key] = {"value": value, "_built_at": _now()}
```

(`capture_hero_image(url, *, prefix, owner_id, date, idx)` — a thin wrapper over `storage.get_client`/`storage.ensure_bucket`/`storage.capture_url` using `storage.media_key_for` — is added in PR3 where the first hero-capturing tool lands; not needed for PR1 and omitted here to avoid an unused-code path. Tracked in the PR3 plan.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_cache.py`
Expected: `PASS insight.cache`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/cache.py scripts/test_cache.py
git commit -m "feat(insight): resolved-window memo cache with TTL"
```

---

### Task 10: `insight/scan.py` — per-shape window walkers

**Files:**
- Create: `looki_mcp/insight/scan.py`
- Test: `scripts/test_scan.py`

**Interfaces:**
- Produces:
  - `iter_dates(start: str, end: str) -> list[str]` (inclusive YYYY-MM-DD list; pure).
  - `async def walk_files(client, moment_id, *, max_calls) -> dict` → `{items, calls_used, capped}` following `cursor_id`/`has_more` via `governed_get`.
  - `async def walk_journals(client, *, cursor_date, max_days, max_calls) -> dict` (date-cursor, `max_days≤31`/call).
  - `async def page_search(client, query, *, start_date=None, end_date=None, max_pages, page_size=20) -> dict`.
- Consumes: `governed_get` (Task 2), `unwrap` (existing).

- [ ] **Step 1: Write the failing test** — `iter_dates` (pure) + `walk_files` paging/budget against a `MockTransport`; patch `asyncio.sleep` to no-op.

```python
# scripts/test_scan.py
"""Tests for insight.scan walkers. Run: .venv/bin/python scripts/test_scan.py"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
import looki_mcp.insight.scan as scan  # noqa: E402

def test_iter_dates_inclusive():
    assert scan.iter_dates("2026-06-01", "2026-06-03") == ["2026-06-01","2026-06-02","2026-06-03"]

def test_walk_files_paginates_and_caps():
    pages = {None: ("c1", [1,2]), "c1": ("c2", [3,4]), "c2": (None, [5])}
    def handler(request):
        cur = request.url.params.get("cursor_id")
        nxt, items = pages[cur]
        return httpx.Response(200, json={"code":0,"detail":"ok","data":{"items":items,"next_cursor_id":nxt,"has_more":nxt is not None}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x") as c:
            full = await scan.walk_files(c, "M1", max_calls=10)
            capped = await scan.walk_files(c, "M1", max_calls=2)
            return full, capped
    full, capped = asyncio.run(run())
    assert full["items"] == [1,2,3,4,5] and full["capped"] is None
    assert capped["calls_used"] == 2 and capped["capped"] == "budget"
    assert capped["items"] == [1,2,3,4]

def main():
    import asyncio as _a
    orig = _a.sleep
    async def _nosleep(*a, **k): return None
    _a.sleep = _nosleep  # type: ignore
    try:
        test_iter_dates_inclusive(); test_walk_files_paginates_and_caps()
    finally:
        _a.sleep = orig  # type: ignore
    print("\033[32mPASS\033[0m insight.scan")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_scan.py`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# looki_mcp/insight/scan.py
"""Per-shape API window walkers. The Looki endpoints do NOT share a pagination
contract (bare lists with no cursor; /files uses cursor_id; /journals uses a DATE
cursor capped at 31 days/call; /search is page-based). So this exposes one walker
PER shape rather than a single leaky abstraction. Every networked walk routes
through client.governed_get (rate governor + 429 backoff) and reports calls_used
+ capped ("budget" when max_calls is hit).
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any

import httpx

from looki_mcp.client import governed_get, unwrap


def iter_dates(start: str, end: str) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    out, d = [], d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


async def walk_files(client: httpx.AsyncClient, moment_id: str, *, max_calls: int) -> dict:
    items: list[Any] = []
    cursor, calls, capped = None, 0, None
    while True:
        if calls >= max_calls:
            capped = "budget"
            break
        params = {"limit": 100}
        if cursor:
            params["cursor_id"] = cursor
        resp = await governed_get(client, f"/moments/{moment_id}/files", params=params)
        calls += 1
        data = unwrap(resp) or {}
        items.extend(data.get("items", []) if isinstance(data, dict) else [])
        cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
        if not (isinstance(data, dict) and data.get("has_more") and cursor):
            break
    return {"items": items, "calls_used": calls, "capped": capped}


async def walk_journals(client: httpx.AsyncClient, *, cursor_date: str | None, max_days: int, max_calls: int) -> dict:
    items: list[Any] = []
    cursor, calls, capped, remaining = cursor_date, 0, None, max_days
    while remaining > 0:
        if calls >= max_calls:
            capped = "budget"
            break
        chunk = min(31, remaining)
        params = {"max_days": chunk}
        if cursor:
            params["cursor_date"] = cursor
        resp = await governed_get(client, "/journals", params=params)
        calls += 1
        data = unwrap(resp) or {}
        items.extend(data.get("items", []) if isinstance(data, dict) else [])
        remaining -= chunk
        cursor = data.get("next_cursor_id") if isinstance(data, dict) else None
        if not (isinstance(data, dict) and data.get("has_more") and cursor):
            break
    return {"items": items, "calls_used": calls, "capped": capped}


async def page_search(client: httpx.AsyncClient, query: str, *, start_date: str | None = None,
                      end_date: str | None = None, max_pages: int, page_size: int = 20) -> dict:
    items: list[Any] = []
    page, calls, capped = 1, 0, None
    while True:
        if calls >= max_pages:
            capped = "budget"
            break
        params: dict = {"query": query, "page": page, "page_size": page_size}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = await governed_get(client, "/moments/search", params=params)
        calls += 1
        data = unwrap(resp) or {}
        items.extend(data.get("items", []) if isinstance(data, dict) else [])
        if not (isinstance(data, dict) and data.get("has_more")):
            break
        page += 1
    return {"items": items, "calls_used": calls, "capped": capped}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_scan.py`
Expected: `PASS insight.scan`.

- [ ] **Step 5: Commit**

```bash
git add looki_mcp/insight/scan.py scripts/test_scan.py
git commit -m "feat(insight): per-shape API window walkers"
```

---

### Task 11: Refactor `describe_realtime_event` onto the insight layer

**Files:**
- Modify: `looki_mcp/tools/realtime.py` (replace `_forge_describe_image` usage with `insight.llm.describe_image`; emit the envelope)
- Test: `scripts/test_realtime_describe.py` (characterization)

**Interfaces:**
- Consumes: `insight.llm.describe_image`, `insight.envelope.render`.
- Produces: `describe_realtime_event` returns the envelope `{data: {event, image_url}, narrative: <caption|null>, meta: {vlm_used}}`. Behavior identical when `FORGE_URL` is set (caption still produced).

- [ ] **Step 1: Write the failing characterization test** — monkeypatch `insight.llm.describe_image` and the Looki call; assert the new envelope shape + that `vlm_used` reflects whether a caption came back.

```python
# scripts/test_realtime_describe.py
"""Characterization test for the refactored describe_realtime_event.
Run: .venv/bin/python scripts/test_realtime_describe.py"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import looki_mcp.insight.llm as llm  # noqa: E402
from fastmcp import FastMCP  # noqa: E402
from looki_mcp.tools.realtime import register_realtime_tools  # noqa: E402

class _FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): return None
    def json(self): return {"code": 0, "detail": "ok", "data": self._p}

def _get_tool(fn_name):
    mcp = FastMCP(name="t")
    register_realtime_tools(mcp)
    return mcp  # tools registered; we call the underlying coroutine via the module

async def scenario(caption):
    # Patch the Looki client + the VLM call.
    import looki_mcp.tools.realtime as rt
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _FakeResp({"description":"walking","file":{"temporary_url":"http://x/s.jpg"}})
    rt.get_client = lambda: _Client()  # type: ignore
    async def fake_desc(url, prompt, **k): return caption
    llm.describe_image = fake_desc  # type: ignore
    # call the tool function directly
    return await rt._describe_realtime_event_impl()

def test_envelope_with_caption():
    out = json.loads(asyncio.run(scenario("a person walking")))
    assert out["data"]["event"]["description"] == "walking"
    assert out["data"]["image_url"] == "http://x/s.jpg"
    assert out["narrative"] == "a person walking"
    assert out["meta"]["vlm_used"] is True

def test_envelope_without_caption():
    out = json.loads(asyncio.run(scenario(None)))
    assert out["narrative"] is None and out["meta"]["vlm_used"] is False

def main():
    test_envelope_with_caption(); test_envelope_without_caption()
    print("\033[32mPASS\033[0m realtime.describe refactor")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python scripts/test_realtime_describe.py`
Expected: FAIL — `_describe_realtime_event_impl` doesn't exist yet / old shape returned.

- [ ] **Step 3: Write minimal implementation** — in `looki_mcp/tools/realtime.py`: extract the tool body into a module-level `async def _describe_realtime_event_impl()` that the registered tool delegates to, swap the Forge call for `insight.llm.describe_image`, and return the envelope. Keep `_extract_image_url`. Delete the now-dead `_forge_describe_image` + its Langfuse plumbing (that tracing moves behind `insight.llm` in a later task/PR; for now drop it from realtime).

```python
from looki_mcp.insight import llm as insight_llm
from looki_mcp.insight.envelope import render

async def _describe_realtime_event_impl() -> str:
    try:
        async with get_client() as client:
            response = await client.get("/realtime/latest-event")
            payload = unwrap(response)
        image_url = _extract_image_url(payload)
        narrative = await insight_llm.describe_image(
            image_url, "Describe the most important real-world event or activity in this image in one concise sentence.",
        ) if image_url else None
        return render(
            {"event": payload, "image_url": image_url},
            narrative=narrative,
            meta={"vlm_used": narrative is not None},
        )
    except Exception as exc:
        return f"Error: {format_error(exc)}"
```

Then the registered `describe_realtime_event` tool body becomes `return await _describe_realtime_event_impl()`. Remove the `import os` Forge/Langfuse blocks that are now unused in this file.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python scripts/test_realtime_describe.py`
Expected: `PASS realtime.describe refactor`.

- [ ] **Step 5: Run the existing helper tests to confirm no regressions, then commit**

```bash
.venv/bin/python scripts/test_journals_helpers.py
git add looki_mcp/tools/realtime.py looki_mcp/insight/__init__.py scripts/test_realtime_describe.py
git commit -m "refactor(realtime): describe_realtime_event onto insight.llm + envelope"
```

---

## Self-Review

**Spec coverage (PR1 scope = §3 Insight Core + the realtime refactor):**
- governor.py → Task 1 ✓ · client 429 backoff → Task 2 ✓ · llm.py (config/degradation/openai/anthropic/gemini/caption) → Tasks 3–6 ✓ · envelope.py → Task 7 ✓ · storage.media_key_for → Task 8 ✓ · cache.py → Task 9 ✓ · scan.py → Task 10 ✓ · describe_realtime_event refactor + char test [A2] → Task 11 ✓.
- `geo.py`, `temporal.py`, `journal_mine.py` and the 10 tools are **PR2/PR3** (their own plans) — intentionally out of PR1 scope.
- `capture_hero_image` deferred to PR3 (first hero-capturing tool) and explicitly noted in Task 9 to avoid dead code.

**Placeholder scan:** no "TBD"/"add error handling"/"similar to Task N" — every code step shows real code. The one forward-reference (`_provider_*` in Task 4) is explicitly stubbed-then-implemented in Task 5, with the try/except guaranteeing degradation in between.

**Type consistency:** `resolve_provider()` dict keys (`provider/base_url/api_key/model/vlm_model`) are used identically in Tasks 3–6; `governed_get(client, url, *, params, max_retries)` signature matches its callers in `scan.py`; walker return dicts use the same `{items, calls_used, capped}` shape consumed by tools in PR2/PR3; `render(data, *, narrative, meta)` matches Task 11's call.

---

## Execution Handoff

PR2 (LLM-free tools: `journal_mine`/`geo`/`temporal` + `commitment_harvester`/`the_unwritten`/`places_of_my_life`) and PR3 (deep + vision tools) each get their own plan authored **after** PR1 lands, so their task code binds to the real, merged Insight Core interfaces rather than speculative ones.
