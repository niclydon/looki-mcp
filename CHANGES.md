# Changes

Chronological per-phase log. Each entry points at the long-form story in
`docs/narrative/`.

## 2026-06-21 — Journals API tools + MinIO media capture (14 → 24 tools)

Added full support for the new Looki `/journals` endpoint family and durable
capture of journal media to MinIO. Tool count `14 → 22 → 24`. Not yet committed
or deployed — production (`/services/looki-mcp`, port 7861) still runs the old
14-tool code.

**Mapping.** Live-probed the endpoint, then reconciled against the official agent
skill (`web.looki.ai/agent/looki-memory/SKILL.md`). Findings: 4 endpoints
(`/journals`, `/journals/calendar`, `/journals/by_date`, `/journals/{id}`); real
params are `cursor_date` / `max_days`≤31 / `sort_order` (the moments-style
`limit`/`on_date`/`type` are silently ignored); `next_cursor_id` is a **date**;
`items` are per-day **buckets**, and one date can yield multiple buckets; **6**
entry types (not 2): `DIARY`, `YESTERDAY_RECAP`, `DIETARY`, `AUDIO_SUMMARY`,
`STORYBOARD`, `DAILY_ROUTINE`. Data is text-first + AI-generated `IMAGE` only (no
video/audio). Long-form bodies ~2–2.5k chars, ~7 entries/day → token cost is real.
Rewrote `journals_api_findings.md` from a 32-line stub into a validated mapping.

**8 journals tools** (`looki_mcp/tools/journals.py`): required mirrors
`get_journals`, `get_journals_calendar`, `get_journals_by_date`,
`get_journal_entry`; recommended composites `get_recent_journals`,
`get_todays_journal`, `backfill_journals`, `search_journals`. Shared `mode` knob
(`index`/`summary`/`full`, summary default) is the token-discipline answer;
`get_journal_entry` is always full, `backfill_journals` defaults to `index`.
Day-bucket→entry reshaping helpers TDD'd in `scripts/test_journals_helpers.py`.

**Adversarial review #1** (public surface): caught a thumbnail `temporary_url`
JWT leak in summary mode (the unit fixture's `thumbnail: None` made the leak-check
pass vacuously). Fixed `_shape_media` to be fully URL-free, strengthened the
fixture, and restricted `backfill_journals` to `index`/`summary` (no `full`).

**MinIO media capture** (operator requirement — journal image URLs are ~10-min
JWTs): new `looki_mcp/storage.py` (boto3 S3 client, optional-feature pattern,
async-safe via `asyncio.to_thread`, idempotent deterministic keys). Tools
`capture_journal_media` + `backfill_journal_media`; `get_journal_entry`
auto-captures on read (returns `{entry, media_capture}`); listing tools surface a
deterministic `minio_key`. Target: crucible MinIO (`crucible.niclydon.io:9000`),
bucket `looki-journal-media`, key `journals/<date>/<journal_id>/<idx>_source.jpg`.
`boto3>=1.34.0` added to `pyproject.toml` + `requirements.txt`; `MINIO_*` in
gitignored `.env` and documented in `.env.example`. Verified live: a 1.75 MB image
stored + `mc stat`-confirmed; backfill captured 12 images/3 days, 0 failures,
idempotent re-runs.

**Adversarial review #2** (capture layer): fixed unbounded `resp.content`
buffering → streamed download with a 50 MB cap (OOM risk on the long-lived server,
reachable on a normal read); corrected two docstring/return-shape contradictions;
capped the `backfill_journal_media` objects manifest at 250. Kept
`follow_redirects=True` (trusted URL source). Triage rejected 4 misreads (the
"ensure_bucket permanently caches failure" and "permanent capture blackout"
claims were wrong — boto3 client construction is offline and the bucket flag isn't
set on failure).

**Verification.** 3 unit-test scripts (35+ assertions) + smoke + integration +
full 24-tool live suite: 22 PASS, 2 pre-existing moments SKIP, 0 FAIL. Diff: 13
files, ~1,604 insertions.

**Unblocked / pending.** Tools are built and verified on dev (port 3456). Pending:
commit + redeploy the production 7861 service to expose the new tools in the
connected Looki MCP. Optional: `/code-review ultra` before shipping.

Full story: `docs/narrative/2026-06-21-journals-api-and-media-capture.md`
