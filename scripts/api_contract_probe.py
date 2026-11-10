#!/usr/bin/env python3
"""Looki Open API contract re-probe (skill hash + known paths + enum checks).

Use after Looki ships skill/API changes, or as a post-fix baseline for RP-57.

Offline (no credentials)::

    .venv/bin/python scripts/api_contract_probe.py --skill-only

Live (needs LOOKI_BASE_URL + LOOKI_API_KEY in env or .env)::

    set -a; source .env; set +a
    .venv/bin/python scripts/api_contract_probe.py

Never prints the API key. Keeps request count small (serial GETs, paced;
well within the 60 req/min upstream budget).
Exit 0 when skill is reachable and (if live) known paths respond with
envelope code 0 (or expected validation failures for invalid enums).
Exit 1 on hard regressions (auth fail, known path missing, invalid enum accepted).

Baseline skill sha256 prefix at 2026-07-18 discovery: 4c5c991cb1165b91

Re-baselined 2026-10-16 (OB-65518): /for_you/items was retired upstream
(HTTP 400, envelope code 105) and is now asserted as deprecated instead of
expected to succeed; the error-code vocabulary is 100 = invalid params,
105 = deprecated endpoint, 106 = missing auth token; moment payloads are
checked for the search_context field; the journal type vocabulary is the
October 2026 observed set (unknown future types warn, never fail).

Re-baselined 2026-11-09 (OB-69847): /journals/by_date was retired upstream
under the same contract (HTTP 400, envelope code 105) and is now asserted
as deprecated alongside /for_you/items; moment payloads are additionally
shape-checked for audio_summary (string: prose, or a JSON string carrying
topics) and search_context (comma-separated keyword string) on a recent-day
sample; the moment-files pagination expectation is the renamed response
key next_cursor (was next_cursor_id). The upstream skill doc URL returns
404 as of 2026-11-09, so a failed skill fetch warns and the live contract
checks decide the exit code.

Re-baselined 2026-11-09 evening (OB-69900, official-parity pass): live
checks added for the four endpoints the morning probe missed —
/memory/overview, /summaries, /health-reports, /chat/history — asserting
envelope code 0 and the verified key sets (field names only; record
content is never printed); negative assertions added for the false
routes /moments/dates and /journals/dates (HTTP 422 path-param captures
on the detail routes, not endpoints) and the singular variants
(/summary, /health, /chat, /memory -> 404); the /summaries param trap is
asserted (missing type -> 422; date= instead of start_date/end_date ->
HTTP 400 code 100).

CANDIDATE-GENERATION RULE (learned 2026-11-09, OB-69900): future probe
candidates come FIRST from the official CLI command table (@looki-ai/cli:
memory overview, moment list/search/dates/view/files, journal
list/dates/view, summary list, health list, chat history) plus the
looki-personal-memory skill's record types, and only second from
speculative path names. The morning 2026-11-09 probe hand-built its
candidate list and missed all four endpoints above for lack of the exact
names; do not repeat that.
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
# /for_you/items is deliberately NOT here: upstream retired it (see
# DEPRECATED_PATHS below, asserted separately so a revival or re-code of the
# retirement is loud rather than silently absorbed).
KNOWN_PATHS: list[tuple[str, dict | None]] = [
    ("/me", None),
    ("/moments/calendar", {"start_date": "2026-07-01", "end_date": "2026-07-07"}),
    ("/moments", {"on_date": "2026-07-01"}),
    ("/moments/search", {"query": "coffee", "page_size": "1"}),
    ("/journals", {"max_days": "1"}),
    ("/journals/calendar", {"start_date": "2026-07-01", "end_date": "2026-07-07"}),
    ("/realtime/latest-event", None),
]

# Retired paths and the exact retirement contract asserted for each:
# HTTP 400 with envelope code 105 (deprecated endpoint).
DEPRECATED_PATHS: list[tuple[str, dict | None]] = [
    ("/for_you/items", {"limit": "1"}),
    ("/journals/by_date", {"on_date": "2026-07-01"}),
]

# Envelope error-code vocabulary (verified live 2026-10-16, re-verified 2026-11-09):
#   0   = success
#   100 = invalid params
#   105 = deprecated endpoint
#   106 = missing auth token
CODE_INVALID_PARAMS = 100
CODE_DEPRECATED_ENDPOINT = 105
CODE_MISSING_AUTH_TOKEN = 106

# Journal entry types observed live. July 2026 set: DIARY, YESTERDAY_RECAP,
# DIETARY, AUDIO_SUMMARY, COMIC_PAGE, WEEKLY_JOURNAL, SYSTEM_POST (plus the
# rarer STORYBOARD, DAILY_ROUTINE). Added in the October 2026 sample:
# DAILY_HEALTH_REPORT, DAILY_VLOG, MANUAL_AUDIO_SUMMARY, PLOG (DAILY_VLOG
# migrated from a for_you type to a journal type). Unknown types observed in
# the future are warnings, not failures: upstream grows this vocabulary.
KNOWN_JOURNAL_TYPES = frozenset({
    "DIARY",
    "YESTERDAY_RECAP",
    "DIETARY",
    "AUDIO_SUMMARY",
    "MANUAL_AUDIO_SUMMARY",
    "COMIC_PAGE",
    "WEEKLY_JOURNAL",
    "SYSTEM_POST",
    "STORYBOARD",
    "DAILY_ROUTINE",
    "DAILY_HEALTH_REPORT",
    "DAILY_VLOG",
    "PLOG",
})

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


def _body_and_code(r: httpx.Response) -> tuple[dict, object]:
    try:
        body = r.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body, body.get("code")


def probe_live(base_url: str, api_key: str) -> tuple[list[str], int]:
    """Return (failure messages, live request count). Empty failures == success."""
    failures: list[str] = []
    stats = {"requests": 0}

    def get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
        # Serial + paced: one request at a time, 0.15s between calls, so the
        # whole probe stays far inside the 60 req/min upstream budget.
        stats["requests"] += 1
        resp = client.get(url, **kwargs)
        time.sleep(0.15)
        return resp

    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    base = base_url.rstrip("/")
    with httpx.Client(timeout=20.0, headers=headers) as client:
        print("=== known path matrix ===")
        for path, params in KNOWN_PATHS:
            r = get(client, base + path, params=params)
            body, code = _body_and_code(r)
            ok = r.status_code == 200 and code == 0
            flag = "OK" if ok else "FAIL"
            print(f"  {flag} {r.status_code} env={code} {path}")
            if not ok:
                failures.append(f"known path failed: {path} status={r.status_code} code={code}")

        print("=== deprecation assertions (retired paths) ===")
        for path, params in DEPRECATED_PATHS:
            r = get(client, base + path, params=params)
            body, code = _body_and_code(r)
            if r.status_code == 400 and code == CODE_DEPRECATED_ENDPOINT:
                print(f"  OK {path} retired: HTTP 400 env={code} (deprecated endpoint)")
            else:
                failures.append(
                    f"deprecated path contract changed: {path} expected HTTP 400 "
                    f"code={CODE_DEPRECATED_ENDPOINT}, got status={r.status_code} code={code}"
                )
                print(
                    f"  FAIL {path} expected HTTP 400 code={CODE_DEPRECATED_ENDPOINT}, "
                    f"got status={r.status_code} code={code}"
                )

        print("=== auth contract check ===")
        with httpx.Client(timeout=20.0, headers={"Accept": "application/json"}) as anon:
            r = get(anon, base + "/me")
            body, code = _body_and_code(r)
            if code == CODE_MISSING_AUTH_TOKEN:
                print(f"  OK no-key /me rejected code={code} (missing auth token)")
            else:
                failures.append(
                    f"no-key /me should return code={CODE_MISSING_AUTH_TOKEN} "
                    f"(missing auth token), got status={r.status_code} code={code}"
                )
                print(
                    f"  FAIL no-key /me expected code={CODE_MISSING_AUTH_TOKEN}, "
                    f"got status={r.status_code} code={code}"
                )

        print("=== enum contract checks ===")
        # Uppercase sort_order must fail as invalid params (code 100)
        r = get(client, base + "/journals", params={"max_days": 1, "sort_order": "ASC"})
        body, code = _body_and_code(r)
        if code == 0:
            failures.append("expected sort_order=ASC to fail, got code=0")
            print("  FAIL sort_order=ASC accepted")
        elif code != CODE_INVALID_PARAMS:
            failures.append(
                f"sort_order=ASC should fail with code={CODE_INVALID_PARAMS} "
                f"(invalid params), got code={code}"
            )
            print(f"  FAIL sort_order=ASC rejected with unexpected code={code}")
        else:
            print(f"  OK sort_order=ASC rejected code={code} (invalid params)")

        r = get(client, base + "/journals", params={"max_days": 1, "sort_order": "asc"})
        body, code = _body_and_code(r)
        if code != 0:
            failures.append(f"sort_order=asc should succeed, code={code}")
            print(f"  FAIL sort_order=asc code={code}")
        else:
            print("  OK sort_order=asc")

        print("=== journal type vocabulary ===")
        r = get(client, base + "/journals", params={"max_days": 7})
        body, code = _body_and_code(r)
        seen_types: set[str] = set()
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            # /journals wraps its day buckets in a paginated items envelope.
            data = data.get("items")
        if isinstance(data, list):
            for bucket in data:
                if not isinstance(bucket, dict):
                    continue
                entries = bucket.get("journals")
                if not isinstance(entries, list):
                    entries = [bucket]
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("type"):
                        seen_types.add(str(entry["type"]))
        if seen_types:
            print(f"  journal types seen ({len(seen_types)}): {sorted(seen_types)}")
            for t in sorted(seen_types - KNOWN_JOURNAL_TYPES):
                # New upstream types are expected over time: warn, do not fail.
                print(f"  WARN: unknown journal type {t} (not in October 2026 vocabulary)")
        else:
            print("  WARN: no journal entries in sample window for type vocabulary check")

        print("=== moment shape checks ===")
        # FileModel metadata nesting sample + search_context presence
        r = get(client, base + "/moments", params={"on_date": "2026-07-01"})
        body, code = _body_and_code(r)
        moments = body.get("data") if isinstance(body, dict) else None
        if isinstance(moments, list) and moments:
            if "search_context" in moments[0]:
                print("  OK moment payload carries search_context")
            else:
                failures.append("moment payload missing search_context field")
                print("  FAIL moment payload missing search_context field")
            mid = moments[0].get("id")
            r = get(client, f"{base}/moments/{mid}/files", params={"limit": 2})
            data = r.json().get("data") or {}
            # Moment-files pagination key was renamed next_cursor_id ->
            # next_cursor (verified 2026-11-09); the envelope must carry it.
            if "next_cursor" in data:
                print("  OK moment-files payload carries next_cursor pagination key")
            else:
                failures.append(
                    "moment-files payload missing next_cursor pagination key "
                    f"(keys={sorted(data.keys())})"
                )
                print("  FAIL moment-files payload missing next_cursor pagination key")
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
            print("  WARN: no moments for FileModel/search_context sample date")

        print("=== moment audio_summary / search_context shape checks (recent day) ===")
        # audio_summary exists upstream only from 2026-09-15 on, so sample a
        # recent day (today, falling back to yesterday) rather than the July
        # FileModel sample. Individual moments may omit the key or carry a
        # null, so the contract asserted is: across the day's moments the
        # keys appear, and every present non-null value has the documented
        # shape (audio_summary: string; search_context: string).
        from datetime import date as _date, timedelta as _timedelta

        recent_moments: list = []
        for offset in (0, 1):
            day = (_date.today() - _timedelta(days=offset)).isoformat()
            r = get(client, base + "/moments", params={"on_date": day})
            body, code = _body_and_code(r)
            sample = body.get("data") if isinstance(body, dict) else None
            if isinstance(sample, list) and sample:
                recent_moments = sample
                print(f"  shape sample: {len(sample)} moments on {day}")
                break
        if recent_moments:
            dict_moments = [m for m in recent_moments if isinstance(m, dict)]
            if any("audio_summary" in m for m in dict_moments):
                print("  OK recent moment payloads carry audio_summary")
            else:
                failures.append("recent moment payloads missing audio_summary field")
                print("  FAIL recent moment payloads missing audio_summary field")
            bad_audio = [
                m.get("id") for m in dict_moments
                if m.get("audio_summary") is not None
                and not isinstance(m.get("audio_summary"), str)
            ]
            if bad_audio:
                failures.append(f"audio_summary not a string on moments {bad_audio}")
                print(f"  FAIL audio_summary not a string on moments {bad_audio}")
            else:
                print("  OK audio_summary values are strings (prose or JSON-with-topics) or null")
            if any("search_context" in m for m in dict_moments):
                print("  OK recent moment payloads carry search_context")
            else:
                failures.append("recent moment payloads missing search_context field")
                print("  FAIL recent moment payloads missing search_context field")
            bad_ctx = [
                m.get("id") for m in dict_moments
                if m.get("search_context") is not None
                and not isinstance(m.get("search_context"), str)
            ]
            if bad_ctx:
                failures.append(f"search_context not a string on moments {bad_ctx}")
                print(f"  FAIL search_context not a string on moments {bad_ctx}")
            else:
                print("  OK search_context values are comma-separated keyword strings or null")
        else:
            print("  WARN: no moments today or yesterday for audio_summary shape sample")

        print("=== official-parity endpoints (2026-11-09 evening, OB-69900) ===")
        # Field names only are asserted/printed; record content never is.
        from datetime import date as _pdate, timedelta as _ptd

        _win_end = _pdate.today().isoformat()
        _win_start = (_pdate.today() - _ptd(days=2)).isoformat()

        # /memory/overview: envelope code 0 + the verified key sets.
        r = get(client, base + "/memory/overview")
        body, code = _body_and_code(r)
        data = body.get("data") if isinstance(body, dict) else None
        summaries = data.get("summaries") if isinstance(data, dict) else None
        _summary_keys = {
            "identity", "lifestyle", "traits", "interests", "relationships",
            "current_experiences", "looki_preferences",
        }
        if (
            code == 0
            and isinstance(summaries, dict)
            and _summary_keys <= set(summaries)
            and "updated_at" in data
        ):
            print("  OK /memory/overview code=0; summaries key set + updated_at present")
        else:
            failures.append(
                f"/memory/overview contract changed: status={r.status_code} code={code}"
            )
            print("  FAIL /memory/overview contract changed")

        # /summaries type=daily over a recent 3-day window.
        r = get(
            client,
            base + "/summaries",
            params={"start_date": _win_start, "end_date": _win_end, "type": "daily"},
        )
        body, code = _body_and_code(r)
        data = body.get("data") if isinstance(body, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        if code == 0 and isinstance(items, list) and all(
            isinstance(i, dict) and {"on_date", "summary"} <= set(i) for i in items
        ):
            print(f"  OK /summaries type=daily code=0; {len(items)} items, item keys verified")
        else:
            failures.append(
                f"/summaries contract changed: status={r.status_code} code={code}"
            )
            print("  FAIL /summaries type=daily contract changed")

        # Param traps: missing type -> 422; date= instead of
        # start_date/end_date -> HTTP 400 code 100 (misleading detail).
        r = get(
            client,
            base + "/summaries",
            params={"start_date": _win_start, "end_date": _win_end},
        )
        if r.status_code == 422:
            print("  OK /summaries without type rejected 422 (missing query.type)")
        else:
            failures.append(
                f"/summaries without type should return 422, got status={r.status_code}"
            )
            print(f"  FAIL /summaries without type: status={r.status_code}")
        r = get(client, base + "/summaries", params={"date": _win_end, "type": "daily"})
        body, code = _body_and_code(r)
        if r.status_code == 400 and code == CODE_INVALID_PARAMS:
            print("  OK /summaries date= trap intact: HTTP 400 code=100")
        else:
            failures.append(
                "/summaries date= trap changed: expected HTTP 400 "
                f"code={CODE_INVALID_PARAMS}, got status={r.status_code} code={code}"
            )
            print("  FAIL /summaries date= trap changed")

        # /health-reports over the same window.
        r = get(
            client,
            base + "/health-reports",
            params={"start_date": _win_start, "end_date": _win_end},
        )
        body, code = _body_and_code(r)
        data = body.get("data") if isinstance(body, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        _report_keys = {
            "summary", "calorie", "daily_metrics", "dietary_review",
            "events", "time_range",
        }
        if code == 0 and isinstance(items, list) and all(
            isinstance(i, dict)
            and {"date", "tz", "report_data"} <= set(i)
            and isinstance(i.get("report_data"), dict)
            and _report_keys <= set(i["report_data"])
            for i in items
        ):
            print(f"  OK /health-reports code=0; {len(items)} items, report_data keys verified")
            if not items:
                print("  WARN: no health reports in the sample window")
        else:
            failures.append(
                f"/health-reports contract changed: status={r.status_code} code={code}"
            )
            print("  FAIL /health-reports contract changed")

        # /chat/history first page: pagination fields + item keys.
        r = get(client, base + "/chat/history", params={"limit": 2})
        body, code = _body_and_code(r)
        data = body.get("data") if isinstance(body, dict) else None
        if (
            code == 0
            and isinstance(data, dict)
            and {"items", "has_more", "next_cursor"} <= set(data)
            and all(
                isinstance(i, dict) and {"role", "text", "created_at"} <= set(i)
                for i in data.get("items") or []
            )
        ):
            print("  OK /chat/history code=0; items/has_more/next_cursor verified")
        else:
            failures.append(
                f"/chat/history contract changed: status={r.status_code} code={code}"
            )
            print("  FAIL /chat/history contract changed")

        print("=== false-route assertions (OB-69900) ===")
        # /moments/dates and /journals/dates are NOT routes: the detail
        # routes capture the segment as an id and reject it with 422.
        for path in ("/moments/dates", "/journals/dates"):
            r = get(client, base + path)
            if r.status_code == 422:
                print(f"  OK {path} is a path-param capture (422), not a route")
            else:
                failures.append(
                    f"{path} should return 422 (path-param capture), "
                    f"got status={r.status_code}"
                )
                print(f"  FAIL {path}: status={r.status_code}")
        # Singular variants are plain 404s.
        for path in ("/summary", "/health", "/chat", "/memory"):
            r = get(client, base + path)
            if r.status_code == 404:
                print(f"  OK {path} 404 (not a route)")
            else:
                failures.append(
                    f"{path} should return 404, got status={r.status_code}"
                )
                print(f"  FAIL {path}: status={r.status_code}")

    return failures, stats["requests"]


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
    skill_text = None
    try:
        skill_text, digest = fetch_skill()
    except Exception as exc:
        # Since 2026-11-09 the upstream skill doc URL returns 404 and no
        # OpenAPI/docs routes exist on the API base (OB-69846). The live
        # contract below is the baseline now, so warn and continue; only
        # --skill-only mode (whose sole check is the skill doc) fails here.
        print(f"WARN: could not fetch skill ({exc}); continuing with live checks")
        if args.skill_only:
            return 1
    if skill_text is not None:
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
    started = time.monotonic()
    failures, n_requests = probe_live(base, key)
    elapsed = time.monotonic() - started
    print(f"=== live probe: {n_requests} requests in {elapsed:.1f}s (serial, paced) ===")
    if failures:
        print("=== FAILURES ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("=== all live checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
