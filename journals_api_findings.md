# Looki API Findings: `/journals` Endpoints

**Status:** Authoritative mapping, validated against the live API on **2026-06-20**,
re-checked **2026-07-18** (FileModel `metadata` nesting; `sort_order` must be
lowercase `asc`|`desc`; additional journal types `COMIC_PAGE`, `WEEKLY_JOURNAL`,
`SYSTEM_POST` observed), re-verified **2026-10-16** (retired `/for_you/items`;
new journal types `DAILY_HEALTH_REPORT`, `DAILY_VLOG`, `MANUAL_AUDIO_SUMMARY`,
`PLOG`; `content`/`thumbnail` omission nuances; error codes 105/106), and
updated **2026-11-09** for current endpoint retirements and moment/file fields.
**Verification basis (2026-11-09):** approximately 130 direct API requests from
Furnace, with no rate-limit responses. The upstream agent skill URL now returns
404, and no OpenAPI or documentation routes were found on the API base.
**Sources:** direct live API probes from Furnace. The previous agent-skill
reference is unavailable and is not a current contract source.

## Overview
The Journals feature exposes AI-generated long-form text recaps and a new family of
AI-generated images, organized as **day-grouped buckets**. It complements `/moments`
(raw captured media): journals are the *written* layer of the memory product.

**Retired endpoint (2026-10-16):** `GET /for_you/items` (the former vlogs/comics
feed) is retired - a live probe returned HTTP 400 with envelope code 105
(deprecated endpoint), and the upstream detail points to `GET /journals` instead.
Do not call `/for_you/items`. Its content family now lives in the journals feed:
`DAILY_VLOG` migrated from a for_you type to a journal type.

## Active endpoints (3)
All are `GET`, require the `X-API-Key` header, share the base URL
`https://open.looki.ai/api/v1`, and return the standard `{code, detail, data}` envelope
(`unwrap()` strips it). Rate limit: 60 req/min (HTTP 429 on excess).

| Endpoint | Params | `data` shape |
|---|---|---|
| `/journals` | `cursor_date` (YYYY-MM-DD, optional), `max_days` (int, default **7**, max **31**), `sort_order` (**`asc`\|`desc` lowercase only**, default newest-first) | `{ items: DayBucket[], next_cursor_id: str\|null, has_more: bool }` |
| `/journals/calendar` | `start_date` (req), `end_date` (req) — YYYY-MM-DD | **bare** `[{ date: str }]` — which days have entries |
| `/journals/{id}` | path: journal UUID | a single `JournalEntry` object |

**Retired endpoint (2026-11-09):** `GET /journals/by_date` returns HTTP 400,
envelope code 105; Looki identifies `GET /journals` as its successor. The old
bare-list `DayBucket[]` response shape is historical and must not be treated as
a callable route. The MCP by-date tools were re-implemented over `GET /journals`
in OB-69844 (landed 2026-11-09).

### Param notes (validated live)
- `max_days` counts **distinct days**, not entries (`max_days=2`→2 days, `=14`→14 days). The default with NO params is 7.
- `limit`, `on_date`, `type`, `start_date`/`end_date` are **silently ignored** by `/journals` (they are NOT real params — earlier guesses were wrong; the endpoint fell back to default 7 days).
- `sort_order` live enum is **`asc`/`desc` only** (uppercase `ASC`/`DESC` → envelope code 100). Skill text may still say ASC/DESC — MCP accepts aliases and wires lowercase. Default unset = newest-first.

## Pagination / Backfill (cursor is a DATE)
`next_cursor_id` is a **date string** (e.g. `"2026-06-14"`), not an opaque ID. To page
into history, pass the previous response's `next_cursor_id` as the next request's
`cursor_date`. Validated: `cursor_date=2026-06-15&max_days=3` → returns days
`2026-06-12/13/14` (strictly older than the cursor, DESC).

**Backfill recipe:** loop `GET /journals?max_days=31&cursor_date=<prev next_cursor_id>`
until `has_more == false`. Cap total days to avoid unbounded token cost (journal content
is long — see below).

## Day-bucket structure
`items[]` are **not entries** — they are per-day groupings:
```
DayBucket = {
  date: str,             // the day this bucket represents (YYYY-MM-DD)
  start_date: str|null,  // set on buckets that hold a multi-day entry (range start)
  journals: JournalEntry[]
}
```
A single calendar date can yield **multiple buckets** (e.g. 2026-06-18 returned one
multi-day `STORYBOARD` bucket + the regular single-day bucket).

## JournalEntry model
```
JournalEntry = {
  id: str,                 // UUID — use with /journals/{id}
  type: str,               // see the entry-types table below (incl. 2026-10-16 additions)
  title: str|null,         // present on DIETARY/AUDIO_SUMMARY/STORYBOARD/DAILY_ROUTINE; null on DIARY/YESTERDAY_RECAP
  description: str,        // short lead/summary (always present)
  content: str|null,       // long-form body; null on STORYBOARD/DAILY_ROUTINE.
                           // 2026-10-16: key present + non-null on text types
                           // (DIARY, YESTERDAY_RECAP, AUDIO_SUMMARY,
                           // MANUAL_AUDIO_SUMMARY); omitted entirely (not null)
                           // on media types (COMIC_PAGE, DAILY_VLOG,
                           // DAILY_HEALTH_REPORT, PLOG)
  media_items: MediaItem[],
  date: str,               // YYYY-MM-DD
  start_date: str|null,    // range start for multi-day types (STORYBOARD, DAILY_ROUTINE)
  tz: str,                 // UTC offset, e.g. "-04:00"
  recorded_at: str,        // ISO 8601 — original capture time
  created_at: str          // ISO 8601 — when the entry was generated
}
MediaItem = { source: FileModel, thumbnail: FileModel|null }
// 2026-10-16: media-item `thumbnail` was present only on DAILY_VLOG items in
// the observed sample; omitted entirely (not null) on other journal types.
FileModel  = { temporary_url: str, media_type: str, metadata?: {width, height, duration_ms?} }
// 2026-07: size/duration_ms no longer top-level; prefer metadata
```
The single-entry `/journals/{id}` payload is exactly one `JournalEntry` (same fields as
the embedded list form — no extra detail fields).

## Entry types (validated content characterization; 2026-10-16 additions included)
| type | title | content | media (category) | multi-day | character |
|---|---|---|---|---|---|
| `YESTERDAY_RECAP` | — | **long ~2200c, sectioned** (Recap / Morning Routine / Outdoor Activity / Errands / Dietary / Actionable Suggestions / TODOs) | none | no | flagship written daily recap |
| `DIETARY` | yes | long ~2500c nutrition analysis | 1 × `dietary_image` | no | per-meal log |
| `AUDIO_SUMMARY` | yes | long ~2500c | 1 × `meeting_analysis_cover_image` | no | meeting / audio recap |
| `DIARY` | — | short ~96–184c (often == description) | ~0.6 × `user_event_diary_image` | no | atomic event vignette |
| `STORYBOARD` | yes | none (desc only) | 1 × `storyboard_image` | **yes** | comic-style multi-day recap (rare 2026-07) |
| `DAILY_ROUTINE` | yes | none (desc only) | 1 × `daily_routine_image` | **yes** | periodic routine summary (rare 2026-07) |
| `COMIC_PAGE` | varies | varies | comic image | no | observed 2026-07 |
| `WEEKLY_JOURNAL` | varies | long | varies | multi-day | observed 2026-07 |
| `SYSTEM_POST` | varies | varies | varies | no | observed 2026-07 |
| `DAILY_HEALTH_REPORT` | varies | **omitted** (media type) | health-report media | no | observed 2026-10-16 (14-day, 119-entry sample) |
| `DAILY_VLOG` | varies | **omitted** (media type) | vlog media; media-item `thumbnail` present on this type in the sample | no | migrated from a for_you type to a journal type; observed 2026-10-16 |
| `MANUAL_AUDIO_SUMMARY` | yes | **present, non-null** (text type) | audio-summary media | no | observed 2026-10-16 |
| `PLOG` | varies | **omitted** (media type) | photo-log media | no | observed 2026-10-16 |

Observed mix per recent day: ~5 `DIARY` + 1 `DIETARY` + 1 `YESTERDAY_RECAP`, plus
occasional `STORYBOARD`/`DAILY_ROUTINE`/`AUDIO_SUMMARY` buckets. ≈7 entries/day, and
long-form entries run ~2–2.5k chars — **token cost is real**; tools need summary modes
and day caps.

## Media (AI-generated images)
- All observed `media_type` = `IMAGE` (model permits `VIDEO`/`AUDIO`; none seen in journals).
- URL host observed 2026-11-09: `user-file.looki.ai` (replacing the earlier
  `devo-user-file.looki.ai` host); path category encodes provenance:
  `/processed/{user_event_diary_image|dietary_image|storyboard_image|meeting_analysis_cover_image|daily_routine_image}/...`
- `temporary_url` carries an `x-looki-token` JWT; observed expiry remains about
  **1 hour**. Re-fetch via the entry if stale.

## Mapping to MCP tools
- `/journals/calendar` → `get_journals_calendar(start_date, end_date)` (mirror of `get_moments_calendar`)
- `/journals/{id}`     → `get_journal_entry(journal_id)` (mirror of `get_moment_details`)
- `/journals`          → `get_journals(cursor_date?, max_days?, sort_order?)` (the feed; supports backfill)
- The prior `get_journals_by_date` route mapping is retired with the upstream
  endpoint; its replacement is tracked by OB-69844.
- Convenience (timezone-aware, mirroring `convenience.py`): `get_recent_journals(days)`,
  `get_todays_journal()` (currently affected by the retired by-date route;
  repair tracked by OB-69844), plus a bounded `backfill_journals(...)` looper
  and a client-side `search_journals(query, ...)` (no server-side journal
  search exists).

## Cross-cutting API notes (2026-11-09)

### Error-code vocabulary (envelope `code`)
| code | meaning |
|---|---|
| 0 | success |
| 100 | invalid params (unchanged) |
| 105 | deprecated endpoint - e.g. retired `GET /for_you/items` and `GET /journals/by_date` (HTTP 400) |
| 106 | missing auth token (new) |

### Moment payloads and pagination
Moment payloads observed across the 2026-09-15–2026-11-09 samples carry
`search_context` (a comma-separated keyword string, 34–123 chars) and
`audio_summary` on every sampled key set. `audio_summary` was non-empty on
43–93% of moments by day (5/6 on 2026-11-09); observed values were prose except
one pure-AUDIO sample whose value was a JSON-encoded string with a `topics`
array. Its normalized MCP presentation is tracked in OB-69845. Moment-files
pagination now returns `next_cursor`; the repository's `walk_files` still reads
`next_cursor_id`, so its multi-page walk is not confirmed against the new key.
The runtime reader gap is filed as OB-69849 and is not changed by this
documentation item. The `/journals` feed continues to use date-valued
`next_cursor_id`.

The `/moments/{id}` detail path requires a UUID. Non-UUID segments such as
`audio`, `transcripts`, and `latest` return HTTP 422, envelope code 100; they
are not standalone routes (control-verified 2026-11-09).
### `/me` observed key set
Observed live on 2026-11-09: `birthday`, `first_name`, `gender`, `id`,
`last_name`, `tz`. `email` / `region` / `kind` were absent (already optional
in `looki_mcp/models.py`).
