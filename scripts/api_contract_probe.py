#!/usr/bin/env python3
"""Looki Open API contract re-probe (skill hash + known paths + enum checks).

Use after Looki ships skill/API changes, or as a post-fix baseline for RP-57.

Offline (no credentials)::

    .venv/bin/python scripts/api_contract_probe.py --skill-only

Live (needs LOOKI_BASE_URL + LOOKI_API_KEY in env or .env)::

    set -a; source .env; set +a
    .venv/bin/python scripts/api_contract_probe.py

Never prints the API key. Keeps request count small (serial GETs).
Exit 0 when skill is reachable and (if live) known paths respond with
envelope code 0 (or expected validation failures for invalid enums).
Exit 1 on hard regressions (auth fail, known path missing, invalid enum accepted).

Baseline skill sha256 prefix at 2026-07-18 discovery: 4c5c991cb1165b91
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

SKILL_URL = "https://web.looki.ai/agent/looki-memory/SKILL.md"
BASELINE_SHA256_PREFIX = "4c5c991cb1165b91"

# Known Open API paths from skill + live inventory (relative to LOOKI_BASE_URL).
KNOWN_PATHS: list[tuple[str, dict | None]] = [
    ("/me", None),
    ("/moments/calendar", {"start_date": "2026-07-01", "end_date": "2026-07-07"}),
    ("/moments", {"on_date": "2026-07-01"}),
    ("/moments/search", {"query": "coffee", "page_size": "1"}),
    ("/journals", {"max_days": "1"}),
    ("/journals/calendar", {"start_date": "2026-07-01", "end_date": "2026-07-07"}),
    ("/journals/by_date", {"on_date": "2026-07-01"}),
    ("/for_you/items", {"limit": "1"}),
    ("/realtime/latest-event", None),
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def fetch_skill() -> tuple[str, str]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(SKILL_URL)
        r.raise_for_status()
        text = r.text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def skill_paths(skill_text: str) -> list[str]:
    found = sorted(set(re.findall(r"\{base_url\}(/[a-zA-Z0-9_{}/?-]+)", skill_text)))
    return found


def probe_live(base_url: str, api_key: str) -> list[str]:
    """Return list of failure messages (empty == success)."""
    failures: list[str] = []
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    base = base_url.rstrip("/")
    with httpx.Client(timeout=20.0, headers=headers) as client:
        print("=== known path matrix ===")
        for path, params in KNOWN_PATHS:
            r = client.get(base + path, params=params)
            try:
                body = r.json()
            except Exception:
                body = {}
            code = body.get("code") if isinstance(body, dict) else None
            ok = r.status_code == 200 and code == 0
            flag = "OK" if ok else "FAIL"
            print(f"  {flag} {r.status_code} env={code} {path}")
            if not ok:
                failures.append(f"known path failed: {path} status={r.status_code} code={code}")
            time.sleep(0.15)

        print("=== enum contract checks ===")
        # Invalid group must fail
        r = client.get(base + "/for_you/items", params={"limit": 1, "group": "comic"})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        code = body.get("code") if isinstance(body, dict) else None
        if code == 0:
            failures.append("expected group=comic to fail, got code=0")
            print("  FAIL group=comic accepted")
        else:
            print(f"  OK group=comic rejected code={code}")
        time.sleep(0.15)

        r = client.get(base + "/for_you/items", params={"limit": 1, "group": "vlog"})
        body = r.json()
        if body.get("code") != 0:
            failures.append(f"group=vlog should succeed, code={body.get('code')}")
            print(f"  FAIL group=vlog code={body.get('code')}")
        else:
            print("  OK group=vlog")
        time.sleep(0.15)

        # Uppercase sort_order must fail
        r = client.get(base + "/journals", params={"max_days": 1, "sort_order": "ASC"})
        body = r.json()
        if body.get("code") == 0:
            failures.append("expected sort_order=ASC to fail, got code=0")
            print("  FAIL sort_order=ASC accepted")
        else:
            print(f"  OK sort_order=ASC rejected code={body.get('code')}")
        time.sleep(0.15)

        r = client.get(base + "/journals", params={"max_days": 1, "sort_order": "asc"})
        body = r.json()
        if body.get("code") != 0:
            failures.append(f"sort_order=asc should succeed, code={body.get('code')}")
            print(f"  FAIL sort_order=asc code={body.get('code')}")
        else:
            print("  OK sort_order=asc")
        time.sleep(0.15)

        # FileModel metadata nesting sample
        r = client.get(base + "/moments", params={"on_date": "2026-07-01"})
        body = r.json()
        moments = body.get("data") if isinstance(body, dict) else None
        if isinstance(moments, list) and moments:
            mid = moments[0].get("id")
            r = client.get(f"{base}/moments/{mid}/files", params={"limit": 2})
            data = r.json().get("data") or {}
            items = data.get("items") or []
            if items:
                f = (items[0].get("file") or {})
                has_meta = isinstance(f.get("metadata"), dict)
                top_dur = f.get("duration_ms")
                print(
                    f"  FileModel sample: metadata_present={has_meta} "
                    f"top_level_duration_ms={top_dur!r} keys={list(f.keys())}"
                )
                if not has_meta and top_dur is None:
                    print("  WARN: neither metadata nor top-level duration_ms on sample file")
            else:
                print("  WARN: no files for sample moment")
        else:
            print("  WARN: no moments for FileModel sample date")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-only",
        action="store_true",
        help="Only fetch skill.md and report hash/paths (no live API).",
    )
    args = parser.parse_args()
    _load_dotenv()

    print(f"=== skill: {SKILL_URL} ===")
    try:
        skill_text, digest = fetch_skill()
    except Exception as exc:
        print(f"FAIL: could not fetch skill: {exc}", file=sys.stderr)
        return 1
    print(f"sha256={digest}")
    print(f"sha256_prefix={digest[:16]}")
    if digest.startswith(BASELINE_SHA256_PREFIX):
        print(f"baseline match: yes ({BASELINE_SHA256_PREFIX})")
    else:
        print(
            f"baseline match: NO — skill changed since discovery "
            f"(was {BASELINE_SHA256_PREFIX}…); re-read skill for new endpoints"
        )
    paths = skill_paths(skill_text)
    print(f"skill-documented path templates ({len(paths)}):")
    for p in paths:
        print(f"  {p}")

    if args.skill_only:
        print("=== skill-only mode: live probe skipped ===")
        return 0

    base = os.environ.get("LOOKI_BASE_URL", "").strip()
    key = os.environ.get("LOOKI_API_KEY", "").strip()
    if not base or not key:
        print(
            "WARN: LOOKI_BASE_URL / LOOKI_API_KEY not set — live probe skipped. "
            "Re-run without --skill-only after sourcing .env.",
            file=sys.stderr,
        )
        return 0

    print(f"=== live base: {base} (key length={len(key)}, not printed) ===")
    failures = probe_live(base, key)
    if failures:
        print("=== FAILURES ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("=== all live checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
