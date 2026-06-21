# Looki API Findings: `/journals` Endpoints

**Status:** Authoritative mapping, validated against the live API on **2026-06-20**.
**Sources:** (1) Official Looki agent skill `https://web.looki.ai/agent/looki-memory/SKILL.md`
(the canonical param contract); (2) direct live probing of the user's account (the real
content shape, which the skill doc only sketches with a single `DIARY` example).

## Overview
The Journals feature exposes AI-generated long-form text recaps and a new family of
AI-generated images, organized as **day-grouped buckets**. It complements `/moments`
(raw captured media) and `/for_you/items` (vlogs/comics): journals are the *written*
layer of the memory product.

## Endpoints (4)
All are `GET`, require the `X-API-Key` header, share the base URL
`https://open.looki.ai/api/v1`, and return the standard `{code, detail, data}` envelope
(`unwrap()` strips it). Rate limit: 60 req/min (HTTP 429 on excess).

| Endpoint | Params | `data` shape |
|---|---|---|
| `/journals` | `cursor_date` (YYYY-MM-DD, optional), `max_days` (int, default **7**, max **31**), `sort_order` (`ASC`\|`DESC`, default `DESC`) | `{ items: DayBucket[], next_cursor_id: str\|null, has_more: bool }` |
| `/journals/calendar` | `start_date` (req), `end_date` (req) — YYYY-MM-DD | **bare** `[{ date: str }]` — which days have entries |
| `/journals/by_date` | `on_date` (req, YYYY-MM-DD) | **bare** `DayBucket[]` for that date |
| `/journals/{id}` | path: journal UUID | a single `JournalEntry` object |

### Param notes (validated live)
- `max_days` counts **distinct days**, not entries (`max_days=2`→2 days, `=14`→14 days). The default with NO params is 7.
- `limit`, `on_date`, `type`, `start_date`/`end_date` are **silently ignored** by `/journals` (they are NOT real params — earlier guesses were wrong; the endpoint fell back to default 7 days).
- `sort_order` is documented `ASC`/`DESC` (default `DESC` = newest first). Passing it explicitly produced subtly different ordering in probing; treat as pass-through, default unset = newest-first.

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
  type: str,               // one of the 6 types below
  title: str|null,         // present on DIETARY/AUDIO_SUMMARY/STORYBOARD/DAILY_ROUTINE; null on DIARY/YESTERDAY_RECAP
  description: str,        // short lead/summary (always present)
  content: str|null,       // long-form body; null on STORYBOARD/DAILY_ROUTINE
  media_items: MediaItem[],
  date: str,               // YYYY-MM-DD
  start_date: str|null,    // range start for multi-day types (STORYBOARD, DAILY_ROUTINE)
  tz: str,                 // UTC offset, e.g. "-04:00"
  recorded_at: str,        // ISO 8601 — original capture time
  created_at: str          // ISO 8601 — when the entry was generated
}
MediaItem = { source: FileModel, thumbnail: FileModel|null }
FileModel  = { temporary_url: str, media_type: str, size: int|null, duration_ms: int|null }
```
The single-entry `/journals/{id}` payload is exactly one `JournalEntry` (same fields as
the embedded list form — no extra detail fields).

## The 6 entry types (validated content characterization)
| type | title | content | media (category) | multi-day | character |
|---|---|---|---|---|---|
| `YESTERDAY_RECAP` | — | **long ~2200c, sectioned** (Recap / Morning Routine / Outdoor Activity / Errands / Dietary / Actionable Suggestions / TODOs) | none | no | flagship written daily recap |
| `DIETARY` | yes | long ~2500c nutrition analysis | 1 × `dietary_image` | no | per-meal log |
| `AUDIO_SUMMARY` | yes | long ~2500c | 1 × `meeting_analysis_cover_image` | no | meeting / audio recap |
| `DIARY` | — | short ~96–184c (often == description) | ~0.6 × `user_event_diary_image` | no | atomic event vignette |
| `STORYBOARD` | yes | none (desc only) | 1 × `storyboard_image` | **yes** | comic-style multi-day recap |
| `DAILY_ROUTINE` | yes | none (desc only) | 1 × `daily_routine_image` | **yes** | periodic routine summary |

Observed mix per recent day: ~5 `DIARY` + 1 `DIETARY` + 1 `YESTERDAY_RECAP`, plus
occasional `STORYBOARD`/`DAILY_ROUTINE`/`AUDIO_SUMMARY` buckets. ≈7 entries/day, and
long-form entries run ~2–2.5k chars — **token cost is real**; tools need summary modes
and day caps.

## Media (AI-generated images)
- All observed `media_type` = `IMAGE` (model permits `VIDEO`/`AUDIO`; none seen in journals).
- URL host: `user.file.devo.looki.ai`; path category encodes provenance:
  `/processed/{user_event_diary_image|dietary_image|storyboard_image|meeting_analysis_cover_image|daily_routine_image}/...`
- `temporary_url` carries an `x-looki-token` JWT; observed expiry ~**10 min** (the official
  doc states ~1h generically). Treat as short-lived; re-fetch via the entry if stale.

## Mapping to MCP tools (proposed — see implementation plan)
- `/journals/calendar` → `get_journals_calendar(start_date, end_date)` (mirror of `get_moments_calendar`)
- `/journals/by_date`  → `get_journals_by_date(date)` (mirror of `get_moments_by_date`)
- `/journals/{id}`     → `get_journal_entry(journal_id)` (mirror of `get_moment_details`)
- `/journals`          → `get_journals(cursor_date?, max_days?, sort_order?)` (the feed; supports backfill)
- Convenience (timezone-aware, mirroring `convenience.py`): `get_recent_journals(days)`,
  `get_todays_journal()`, plus a bounded `backfill_journals(...)` looper and a
  client-side `search_journals(query, ...)` (no server-side journal search exists).
