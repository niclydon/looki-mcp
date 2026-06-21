# The Written Layer — Journals API and the Race Against Expiring Images

A new endpoint appeared on the Looki API: `GET /api/v1/journals`. It exposed a
part of the product the MCP server had never touched — the *written* memory.
Long-form daily recaps, dietary and meeting analysis, comic-style storyboards,
and a fresh class of AI-generated images. The wearable had always given us
moments (raw captured media) and highlights (vlogs). Journals were the diary.

The goal was to map that endpoint thoroughly, plan how it should become MCP
tools, and build them — required and recommended — so an assistant could read,
search, and reason over a person's journal in a way that actually fit how an LLM
spends tokens. Midway through, the stakes widened: the journal images are served
behind URLs that expire in about ten minutes, and the operator wanted durable
copies in MinIO before they vanished. This is the record of how both halves got
built across 2026-06-20 and 2026-06-21, and the two adversarial reviews that
changed the shape of the code before it shipped.

The tool count went `14 → 22 → 24`.

## The Map Was Wrong Before It Was Right

The work started from a thin findings stub. `journals_api_findings.md` claimed
two item types (`YESTERDAY_RECAP`, `DIARY`), cursor pagination via
`next_cursor_id`/`has_more`, a couple of image categories, and a single-entry
route. Enough to know the endpoint existed. Not enough to build from.

So the first move was to probe the live API with the operator's own key — a
read-only `GET`, exactly the mapping the goal asked for. The envelope was the
familiar `{code, detail, data}`, and `data` carried `items`, `has_more`, and
`next_cursor_id`. The first surprise came immediately: `items` were not entries.
They were **per-day buckets** — `{date, start_date, journals: [...]}` — and a
request with `limit=5` returned eleven of them. The `type` field lived on the
nested journal entries, not the buckets.

The second surprise was the cursor. `next_cursor_id` came back as `"2026-06-14"`
— a **date string**, not an opaque ID. Pagination into history meant walking
backward by date.

The third surprise undid the findings doc's central claim. There were not two
entry types. There were **six**, across a 52-entry probe window:

| type | count | text | media | multi-day |
|------|------:|------|-------|-----------|
| `DIARY` | 33 | short ~96–184c vignette | ~0.6 × `user_event_diary_image` | no |
| `YESTERDAY_RECAP` | 7 | long ~2,200c, sectioned | none | no |
| `DIETARY` | 6 | titled, ~2,500c nutrition analysis | 1 × `dietary_image` | no |
| `STORYBOARD` | 3 | titled narrative, no content body | 1 × `storyboard_image` | **yes** |
| `AUDIO_SUMMARY` | 2 | titled, ~2,500c | 1 × `meeting_analysis_cover_image` | no |
| `DAILY_ROUTINE` | 1 | titled, description only | 1 × `daily_routine_image` | **yes** |

`STORYBOARD` and `DAILY_ROUTINE` carried a `start_date` — they span a range, and
a single calendar date could return *multiple* buckets (the 2026-06-18 query
returned one multi-day `STORYBOARD` bucket plus the regular single-day bucket).
That detail would later become the single highest-risk piece of the build.

### The params were all guesses, and all wrong

The probing also did something useful by failing. Filter attempts —
`on_date`, `start_date`/`end_date`, `type`, `limit` — were all silently ignored.
Every one returned the same default seven days. The endpoint quietly dropped
unknown parameters and fell back to its default.

The correction arrived from the operator, who pasted the canonical Looki agent
skill from `https://web.looki.ai/agent/looki-memory/SKILL.md`. It was the
authoritative contract the probing couldn't reverse-engineer. The real `/journals`
parameters were `cursor_date`, `max_days` (default 7, max 31), and `sort_order`
(`ASC`/`DESC`) — *not* the moments-style `limit`/`on_date`. And the doc revealed
**two endpoints the probing had never found**: `GET /journals/calendar` (which
days have entries) and `GET /journals/by_date` (entries for one specific day).

Re-validated live, the real params behaved exactly as documented: `max_days=2`
returned two distinct days, `max_days=14` returned fourteen; `cursor_date=2026-06-15`
returned 06-12/13/14 — strictly older than the cursor. The backfill recipe was
now concrete: loop `GET /journals?max_days=31&cursor_date=<prev next_cursor_id>`
until `has_more` is false. `/journals/calendar` returned a bare `[{date}]` array;
`/journals/by_date` returned a bare array of day-buckets.

This is the moment the spec and reality merged. The findings doc was rewritten
from a 32-line sketch into a validated mapping: four endpoints, six types, the
day-bucket structure, the date-cursor backfill, the media categories, and a fact
that would drive everything downstream — long-form entries run 2–2.5k characters,
a day holds roughly seven of them, and token cost is therefore real.

### What kind of data, exactly

When asked directly what the endpoint exposes, the honest answer was: **text
first, AI-generated still images second, and nothing else.** Across the probe
window, 32 media items, all `media_type: "IMAGE"`, each behind a
`source.temporary_url`. Zero video. Zero audio — and that last point is a trap.
There is an `AUDIO_SUMMARY` *type*, but it is a text summary of a meeting with an
AI-generated cover image. No playable audio exists anywhere in the feed. The
journals are the written layer; `/moments` remains where real capture media lives.

## The Token Problem Decides the Tool Surface

A planning fan-out (a six-agent workflow: change-surface inventory, convention
extraction, a three-lens design panel, and a synthesis) produced the tool surface.
The design space was narrower than it looked — the four endpoints mostly wanted to
mirror the existing moments tools — but one real fork ran through every proposal:
a day of seven entries at ~2,500 characters each, fetched naively across a 31-day
window, is a token bomb on the order of 100k+ characters.

The answer was a `mode` knob on every listing tool — `index` (an id/title/date
spine, no bodies), `summary` (the default: content truncated to 600 characters
with a `content_truncated` flag, plus URL-free media metadata), and `full` (the
verbatim API payload). The cheap path became the default everywhere; `full` had
to be asked for. `get_journal_entry` is always full — the deliberate "pay for one
entry" escape hatch — and `backfill_journals` defaults to `index`.

Eight tools landed, four required and four recommended:

| Tier | Tool | Maps to |
|------|------|---------|
| required | `get_journals` | `/journals` (feed + date cursor) |
| required | `get_journals_calendar` | `/journals/calendar` |
| required | `get_journals_by_date` | `/journals/by_date` |
| required | `get_journal_entry` | `/journals/{id}` |
| recommended | `get_recent_journals` | tz-aware composite over `/journals` |
| recommended | `get_todays_journal` | tz-aware composite over `/journals/by_date` |
| recommended | `backfill_journals` | bounded date-cursor walk |
| recommended | `search_journals` | client-side substring search (no server route exists) |

The riskiest code was never a tool — it was the three pure helpers that turn
day-buckets into entries: `_flatten_buckets`, `_shape_entry`, `_by_type_counts`.
A naive flatten that treated `items` as entries, or dropped the second bucket on a
multi-bucket day, would silently lose data. So those were written
test-first: `scripts/test_journals_helpers.py`, a runnable script in the house
style (no pytest dependency), with a fixture carrying one multi-day `STORYBOARD`
bucket plus a seven-entry day. Eighteen assertions, watched fail with a
`ModuleNotFoundError`, then made to pass. `TOOL_COUNT` went `14 → 22`, and the
full 22-tool live suite came back clean — the two `SKIP`s were pre-existing
moments tools with no data that day, not failures.

## The First Review Finds a Leak the Tests Couldn't See

Because this touched a public MCP surface, the diff went through an adversarial
review — four reviewers, each on a distinct lens, each prompted to break the
change rather than bless it. Three of the four independently converged on the
same real bug.

`_shape_media` dropped the full-resolution `source.temporary_url` in summary mode
— correct, because it's a ten-minute JWT and would be a dead link by the time an
agent acted on a listing. But it included the **thumbnail** `temporary_url`
unconditionally. Same short-lived JWT, same problem, leaked anyway, in direct
contradiction of the function's own "URL-free media metadata" docstring and the
`DECISIONS.md` intent.

The sharper finding was *why the tests missed it*: the unit fixture hardcoded
`thumbnail: None`, so the existing "no `x-looki-token` in output" assertion passed
**vacuously**. The live data never had thumbnails either, so the live tests were
equally blind. A reproduction confirmed it precisely — source JWT dropped,
thumbnail JWT present:

```
SRC_JWT leaked:   False
THUMB_JWT leaked: True
```

The fix made `_shape_media` genuinely URL-free (both URLs gone, `has_thumbnail`
left as the presence signal), and the fixture was rewritten to carry a thumbnail
*with* a token so the regression guard actually guards. Triage deferred a real
worst-case — `backfill_journals(mode='full', max_total_days=93)` could emit ~1.6
MB — but it was a triple-non-default escape hatch. The proportionate response was
to forbid `full` on the highest-volume tool entirely: `backfill_journals` now
accepts only `index` or `summary`, and verbatim deep history is read one entry at
a time through `get_journal_entry`. One speculative finding (unbounded `media[]`
per entry) was rejected — the validated mapping shows 0–1 media per entry, never
the multi-image arrays the worry assumed.

## The Requirement That Reframed the Work

Mid-build, the operator added a line that changed the project's weight: *"for the
Journals endpoint, it's extremely important we get copies of the media (if any)
downloaded and captured in MinIO here."*

This was not a nice-to-have. The whole reason summary mode dropped image URLs was
that they expire in ten minutes — a `temporary_url` JWT decoded to `iat 1782011619`,
`exp 1782012219`, exactly 600 seconds. Without durable capture, every journal
image is unrecoverable shortly after it's generated.

The infrastructure was already there. MinIO ran locally on `localhost:9000`, and
a remote instance answered at `crucible.niclydon.io:9000` (mc alias `crucible`)
with buckets like `looki-media`, `imessage-attachments`, and `blink-media`. The
house pattern for talking to it came straight from a sibling: `nexus`'s
imessage-sync used a **boto3** S3-compatible client (`endpoint_url`,
`head_bucket`/`create_bucket`, `put_object` with ASCII-safe metadata,
date-partitioned keys), driven by `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/
`MINIO_SECRET_KEY`/`MINIO_BUCKET`.

Two design forks were genuinely the operator's to make, so they were asked, not
assumed. The answers: capture should happen through **explicit tools plus
auto-capture when `get_journal_entry` reads a single entry** (wide listing tools
stay fast and never auto-download); and the target was the **crucible** instance,
bucket `looki-journal-media`. The crucible credentials were lifted from
`~/.mc/config.json` into the gitignored `.env` without ever printing their bytes.

### The capture layer

`looki_mcp/storage.py` was built on the optional-feature pattern the server
already used for Forge and Langfuse — read `os.environ` directly, degrade to a
`disabled` status when unset, so nothing breaks for users without MinIO. boto3 is
synchronous, so every blocking call (`head_bucket`, `create_bucket`,
`head_object`, `put_object`) is offloaded with `asyncio.to_thread` to keep the
event loop free. Keys are deterministic and idempotent:
`journals/<date>/<journal_id>/<idx>_<source|thumb><ext>`. An existing object is
skipped unless `overwrite=True`.

Two new tools registered: `capture_journal_media` (one entry) and
`backfill_journal_media` (a bounded date-cursor sweep that captures directly from
the feed's still-live URLs). `get_journal_entry` gained the auto-capture side
effect and now returns `{entry, media_capture}`, with failures swallowed into the
report so a capture problem can never break a read. The listing tools gained a
deterministic `minio_key` per image — the durable location, computed for free,
without a per-item storage round-trip that would slow the fast path. `TOOL_COUNT`
went `22 → 24`; `boto3>=1.34.0` joined `pyproject.toml` and `requirements.txt`.

The pure storage helpers (`media_key`, extension and content-type inference,
ASCII-safe metadata, the env-gating logic) got their own seventeen-assertion test
script. Then it was verified against the real crucible instance: a 1,753,119-byte
`DIETARY` image landed at
`journals/2026-06-20/b83cf808-.../0_source.jpg`, confirmed by `mc stat` with its
metadata (`journal_id`, `type`, `category`) intact. `backfill_journal_media`
captured 12 images across 3 days, one already-captured, **zero failures**.
Re-running reported `already_captured` — idempotency held. Thirteen objects sat
in `looki-journal-media` by the end.

## The Second Review Catches the OOM, Rejects Four Misreads

The capture layer writes to external storage with credentials over the network on
a long-lived process — higher blast radius — so it earned its own adversarial
review. This one was more interesting for what it *rejected* than what it caught.

The one confirmed must-fix: `capture_url` did `data = resp.content`, buffering an
entire HTTP body into RAM with no size cap. Journal images are ~1–2 MB, but a
pathological or redirect-swapped body — reachable even on a normal
`get_journal_entry` read, since capture runs transparently there — could OOM the
server. The fix streams the download with a hard 50 MB ceiling, rejecting on a
declared `Content-Length` over the cap and again mid-stream in case the header
lies. `follow_redirects=True` was deliberately *kept*: the URL comes from the
trusted Looki API, flipping it to `False` risks silently storing a redirect body,
and triage had already deferred the SSRF angle for exactly that trust-boundary
reason. Two cheap doc-contract corrections went in alongside, and the
`backfill_journal_media` response gained a `_BACKFILL_OBJECTS_CAP` of 250 so a
large sweep returns counts plus a sample rather than thousands of report dicts.

What the triage *rejected* is the part worth recording. Two findings claimed the
capture layer could wedge permanently — `ensure_bucket` "caching a failure state"
forever, and `get_client` "permanently blacked out" after MinIO goes down. Both
misread the code. `_ensure()` only wraps `head_bucket` in its `try`; if
`create_bucket` raises, the exception propagates and `_bucket_ensured = True` is
never reached, so it retries on the next call and recovers cleanly. And
`boto3.client("s3")` construction is purely local — it builds an object, it does
not open a connection, so "MinIO unreachable" never triggers the cached-`None`
path the finding described. A speculative "URLs expire during a multi-page
backfill" was rejected too: a 10-minute TTL dwarfs the few seconds of page
latency, and an expired URL already surfaces as a per-object `failed` without
breaking the sweep. The streamed re-test confirmed the fix didn't break the real
download — 1,753,119 bytes again, non-zero, not an empty redirect body.

## Where It Stands

Twenty-four tools register and pass. Three unit-test scripts (35+ assertions),
the smoke test, the integration test, and the full 24-tool live suite all come
back green — twenty-two `PASS`, two pre-existing moments `SKIP`s, zero `FAIL`.
The diff is 13 files, ~1,600 insertions: a new `storage.py`, a 700-line
`journals.py`, the reference models, the three test scripts, and the docs.

One operational reality matters for anyone picking this up. The work was tested on
a **dev** instance on port 3456, started with the origin-secret guard disabled.
**Production** is a separate systemd service running the *old* 14-tool code from
`/services/looki-mcp` on port 7861 — and note that path, because the repo's own
`systemd/looki-mcp.service` unit claims `/opt/looki-mcp`, which is not where prod
actually lives. The new tools will not appear in the connected Looki MCP until
that 7861 service is redeployed. Nothing here has been committed; the change sits
in the working tree awaiting the operator's word.

See `CHANGES.md` for the chronological per-phase summary.
