# Design: Looki "Magic" Composite MCP Tools

**Status:** v2 — revised after adversarial review; ready for implementation planning
**Date:** 2026-06-24
**Author:** Nic Lydon (with Claude)
**Repo:** `github.com/niclydon/looki-mcp` (public / open-source)

> **v2 changelog (post adversarial review).** A 6-lens adversarial review (API-reality,
> degradation, rate/perf, architecture, privacy, scope) ran against v1. Three lenses
> completed and **converged on the same blockers**; three were cut off by a transient
> provider throttle and were adjudicated by hand. Changes folded in:
> - **B1** `places_of_my_life` redesigned — `location` is on `cover_file`/files, *not* the
>   moment, so v1's per-moment harvest was budget-infeasible. Now cover_file-default +
>   opt-in `deep`.
> - **B2** Added a real throughput **governor** (`insight/governor.py`) + 429 backoff in
>   `client.py`. `scan.py`'s call-count budget was never a per-minute limiter.
> - **B3** Journal section parsing is now **best-effort with a `parsed_section` flag** and a
>   full-content fallback — the headings it keys on are observed, not contractual.
> - **M1–M9, m1–m2, P1–P2, A1–A2, S1** folded in (see inline `[Rn]` tags).
> - **S1** OCR merged into `visual_search` as a mode; **`year_in_review`** added as the 10th.

---

## 1. Overview & Goal

`looki-mcp` currently exposes **24 tools over 12 Looki API endpoints**. Every endpoint and
documented query parameter is already covered (verified 2026-06-24).

This design adds **10 new "magic" composite tools** that combine **2+ endpoints (or an
endpoint + a pluggable LLM/VLM)** to produce results impossible from a single call — the
latent value in fields the single-endpoint tools never cross-reference: per-file `location`
strings, `start_time`/`end_time`/`recorded_at`/`duration_ms` timestamps, the six journal
types (incl. `YESTERDAY_RECAP`'s *Actionable Suggestions / TODOs* section), and the pixels
inside captured photos.

The bar each tool clears: (1) combines 2+ endpoints (or endpoint + VLM/LLM); (2) produces
something impossible from one call; (3) genuinely useful **or** jaw-dropping (ideally both);
(4) feasible under §2, **including graceful degradation with no LLM provider**.

After this work: **34 tools.**

---

## 2. Constraints & Principles

| # | Constraint | Consequence |
|---|---|---|
| C1 | **Public repo — no private-homelab hard deps.** | Forge / MinIO / Langfuse all optional. |
| C2 | **Provider-agnostic LLM/VLM.** | One abstraction (`insight/llm.py`): `none`/`openai`/`anthropic`/`gemini`/`openai_compatible`. Forge = an `openai_compatible` option. **[M5]** Gemini gets its own adapter (image + json-schema paths diverge from OpenAI compat). |
| C3 | **Graceful degradation.** | Every tool returns useful structured JSON with zero LLM config; LLM/VLM is additive, silently skipped when unconfigured, never raises. **[B3]** "useful with zero LLM" must survive heading drift — see journal_mine. |
| C4 | **Tiered cost/latency.** | Most tools snappy; deep flagships (`places_of_my_life` deep mode, `life_rhythm`, `people_and_meetings_intel`, `visual_search`, `auto_biography_chapter`, `year_in_review`) may run 10–60s + use cache. |
| C5 | **60 req/min — enforced by a governor, not a counter.** **[B2]** | `scan.py` bounds scan *scope*; `insight/governor.py` enforces *throughput* (token-bucket ~50/min + jitter) and ALL insight Looki + VLM calls route through it. `client.py` honors 429 `Retry-After`. `meta.capped` distinguishes budget-cap vs 429. |
| C6 | **`temporary_url` JWTs expire ~10–60 min.** | Durable artifacts captured to object storage while live. **[M4]** VLM jobs download bytes while the JWT is fresh and pass base64/stored URLs to the model rather than the ephemeral URL. |
| C7 | **No server-side journal search.** | Scan day-buckets + filter client-side. **[m2]** Flatten via `_flatten_buckets`; multi-day buckets cover `[start_date, date]`. |
| C8 | **`location` is free-text, sometimes null, and NOT a moment field.** **[B1]** | It lives on `cover_file` and per-file. Geo tools default to `cover_file.location` (1 call/day); per-file harvest is opt-in. |
| C9 | **`realtime` is beta / maybe disabled.** | No tool useless without it. |
| **C10** | **Privacy: enabling an LLM provider sends personal data off-box.** **[P1]** | Photos, journal text, locations, people's names go to a third-party API. Requires explicit disclosure (README + `.env.example` + server instructions + per-tool docstrings) and secret/trace hygiene (**[P2]**). See §6.1. |

**Hybrid output contract.** Every new tool returns `{ "data": <structured>, "narrative":
<string|null>, "meta": {...} }`. `data` always populated; `narrative` only when an LLM is
configured. **[m1]** `meta` is a **mandatory uniform contract**:
`{calls_used, days_scanned, capped, cache_hit, vlm_used, enrichment_skipped_reason}`.
Truncation/feasibility signals live ONLY in `meta`, never in `data`. The existing 24 tools
keep returning raw API JSON; the server `instructions` documents the split ("insight tools
return the envelope; endpoint mirrors return raw JSON"). **[m1/A2]** `describe_realtime_event`
migrates onto `insight/llm.py` AND onto the envelope (`{data:event, narrative, meta}`), with a
characterization test asserting identical behavior when `FORGE_*` is set.

---

## 3. Architecture: the "Insight Core" (Approach A)

```
looki_mcp/
  insight/
    governor.py     # [B2] shared async throughput governor (token-bucket ~50/min + jitter)
    llm.py          # [C2/M5] provider-agnostic LLM/VLM: openai_compat + anthropic + gemini adapters
    scan.py         # [M1] per-shape window walkers (NOT one unified paginator)
    geo.py          # [C8/B1] location-string normalize + cluster (heuristic; LLM-upgraded)
    temporal.py     # weekday×hour baselines, anomaly scoring (pure fns)
    journal_mine.py # [B3] best-effort section/people extraction + parsed_section flag
    cache.py        # [M2] object-storage memo cache keyed on RESOLVED window + TTL
    envelope.py     # [A1] PURE serializer of {data,narrative,meta} — does NOT call llm.py
  tools/
    insight_memory.py       # on_this_day_rewind, auto_biography_chapter, the_unwritten, year_in_review
    insight_patterns.py     # life_rhythm, what_was_different
    insight_places.py       # places_of_my_life
    insight_productivity.py  # commitment_harvester, people_and_meetings_intel
    insight_vision.py       # visual_search  (search + ocr modes)
```

Also touched: **`client.py`** gains 429 `Retry-After` backoff + routes through the governor;
**`storage.py`** gains a generic `media_key(prefix, owner_id, date, idx, kind, url)` **[M7]** so
moment/for_you hero images don't collide with the `journals/` tree.

### 3.1 `insight/llm.py` — provider-agnostic LLM/VLM
Generalizes `realtime.py`'s `_forge_describe_image`. Env: `LOOKI_LLM_PROVIDER` (default
`none`), `LOOKI_LLM_BASE_URL`, `LOOKI_LLM_API_KEY`, `LOOKI_LLM_MODEL`, `LOOKI_VLM_MODEL`.
Back-compat: `FORGE_URL` set + provider unset ⇒ auto `openai_compatible`. **Three** request
adapters: OpenAI chat-completions (`openai`/`openai_compatible`), Anthropic Messages, and
**[M5]** a Gemini adapter (its `response_schema`/`response_mime_type` for `extract_json` and its
image-part shape). Interface (async, best-effort, return `None`/`[…None]`, never raise):
`llm_configured()`, `vlm_configured()`, `describe_image`, `caption_images(concurrency=4)`,
`synthesize`, `extract_json`. **[M5]** On a configured-but-failed structured call, set
`meta.enrichment_skipped_reason` rather than silently nulling. httpx REST, no SDK deps.
**[P2]** Never log the API key; Langfuse logs metadata (lengths) only, not content/bytes.

### 3.2 `insight/governor.py` **[B2]** — throughput governor
A process-singleton async token-bucket targeting ~50 req/min with small jitter, plus a
bounded `Semaphore`. `async with governor.slot(): ...` wraps every Looki call (via a
`client.py` helper) and every VLM call. Replaces the unbounded `asyncio.gather` precedent in
`convenience.py`. On HTTP 429, `client.py` honors `Retry-After` and the governor backs off;
the tool surfaces `meta.capped="rate_limit"` vs `meta.capped="budget"`.

### 3.3 `insight/scan.py` **[M1]** — per-shape walkers
Not one paginator — the API has ≥3 styles. Provides: `iter_dates()` (bare-list endpoints:
`/moments`, calendars — no cursor), `walk_files(moment_id)` (`cursor_id`), `walk_journals()`
(date-cursor, `max_days≤31`, reusing the existing `backfill_journals` loop), `page_search()`
(page/page_size). Each returns `{items, calls_used, capped}` and routes through the governor.

### 3.4 `insight/geo.py` **[C8/B1]**
`normalize_location()` + heuristic `cluster_locations()` (token-overlap/prefix; zero LLM);
optional `llm.extract_json` upgrade. Null/empty → `unknown` bucket, counted separately.

### 3.5 `insight/temporal.py`
`build_baseline(moment_days)` (weekday×hour histograms, typical place/slot, daily density),
`score_anomaly(day, baseline)`. Pure, unit-testable. Owns the baseline logic so neither tool
module imports the other **[A-cleanliness]**.

### 3.6 `insight/journal_mine.py` **[B3]**
`extract_todo_section(entry)` matches a **set of heading variants** case-insensitively AND
falls back to bullet/checkbox/`TODO:`/imperative-line detection across the whole body; when no
heading matches it returns the full (bounded) content with `parsed_section: False` and a count
of candidate lines — never a silent empty. `extract_people(entry)` heuristic, LLM-upgraded.
Fixture-tested against **multiple** real `YESTERDAY_RECAP`/`AUDIO_SUMMARY` bodies.

### 3.7 `insight/cache.py` **[M2]**
Wrapper over `storage.py`. Keys on the **resolved concrete window** (`start_date`,`end_date`)
or (`today_local`,`days`) — never the relative arg alone — plus a `built_at`/TTL so a
rolling-window entry expires at the day boundary. `capture_hero_image(url)` reuses
`storage.capture_url` with the new generic `media_key`. No-op in-process when MinIO unset; the
in-process layer is a **process-lifetime singleton** so within a session the second call is
warm **[M3]**.

### 3.8 `insight/envelope.py` **[A1]**
**Pure serializer** of `{data, narrative, meta}`. Does NOT call `llm.py`; tools that want a
narrative call `llm.synthesize` themselves and pass the string in (keeps the LLM dependency
out of every tool's output path and makes envelope trivially testable).

---

## 4. The 10 Tools

Tier: ⚡ snappy / 🐢 deep. Each always-returns `data`; `meta` carries the uniform contract.

### 4.1 `on_this_day_rewind(lookback_years=3, window_days=2)` — ⚡ nostalgia
Combines `journals/by_date` + `moments?on_date` + `for_you/items` for the same calendar day
across prior years. **[M6]** Call budget = anniversaries(`lookback_years`) × dates(`window_days`)
× {by_date, moments} + **one ranged** `for_you` call per anniversary via `recorded_from/to`;
the formula + worst-case count are stated in `meta`. Enrichment: "then vs now" narrative.
Degraded: memories + journal text + highlight links.

### 4.2 `places_of_my_life(days=30, top_n=15, deep=False)` — 🐢 geo *(flagship)* **[B1]**
**Default (snappy-ish):** harvest `cover_file.location` from the `/moments?on_date=` day lists
(1 call/day, no per-moment fan-out); rank places by visit-frequency + time-spent (moment
`start_time`/`end_time` joined to `cover_file.location`); `/files` called only for the `top_n`
places' hero photos. **`deep=True`:** per-moment `/files` location harvest with a documented
call multiplier, governed + `capped`-reported. `meta` reports `located_vs_skipped`. Null
locations → `unknown` bucket. Enrichment: VLM hero captions; LLM merges fuzzy variants.
Degraded: ranked list + stats + samples (zero LLM).

### 4.3 `commitment_harvester(days=14)` — ⚡ productivity **[B3]**
Combines `journals` YESTERDAY_RECAP *Actionable/TODOs* + AUDIO_SUMMARY (`walk_journals` +
`journal_mine`). Data: commitments grouped by source date with verbatim line + entry id, plus
`parsed_section` flag per entry. **When no heading matches, returns bounded full content +
candidate-line count** (never silent empty) — this preserves C3. Enrichment: LLM
dedupe/normalize/owner/age/stale.

### 4.4 `life_rhythm(weeks=4)` — 🐢 quantified-self *(flagship)* **[M9]**
Combines `moments/calendar` + `moments` per active day + `journals` DAILY_ROUTINE/YESTERDAY_RECAP
(`scan` + `temporal`) under an explicit `max_calls`; `meta` carries `days_scanned/calls_used/
capped`. Data: weekday×time histograms, typical place/slot, density, routine blocks.
Enrichment: "your typical Tuesday" narrative. Cache keyed on resolved window; baseline reused
by 4.5.

### 4.5 `what_was_different(date)` — ⚡ (deep-on-cold) quantified-self **[M3]**
Target day's `moments` vs a rolling baseline from 4.4 + that day's `journals`. Warm cache →
snappy. **Cold cache (default MinIO-off, first call of a session): builds the baseline itself —
this is a deep scan, so the tool is honestly re-tiered "deep-on-cold"** and surfaces
`meta.baseline_source: cached|rebuilt`. To bound cold cost it may use a smaller calendar-only
density baseline flagged `baseline_approximate: true`. Data: deviations vs baseline.
Enrichment: narrative.

### 4.6 `people_and_meetings_intel(days=30)` — 🐢 productivity *(flagship)* **[B3]**
Combines `journals` AUDIO_SUMMARY + DIARY + `moments/search`. Heuristic people/topic/action
extraction (`journal_mine`, tolerant per B3). Enrichment: LLM entity/action extraction; VLM
whiteboard OCR. Degraded: grouped raw summaries + counts. Cache keyed on resolved window.

### 4.7 `visual_search(query, mode="match", days=30, max_photos=12)` — 🐢 visual/VLM *(flagship)* **[S1/M4/M8]**
`moments/search` (narrow) → `walk_files` → VLM over each photo. **Two modes:** `match`
(rank photos against a visual query) and `ocr` (extract text — menus/whiteboards/receipts/
signs; absorbs the former `read_the_text_i_saw`). **[M8]** `max_photos` default **12** (validated
cap), per-image VLM timeout < 30s, timeouts → `vlm_used:"partial"`. **[M4]** Downloads photo
bytes while the JWT is fresh and passes base64/stored URLs to the VLM (not the ~10-min
`temporary_url`). `/files` calls counted against the governor budget. Degraded (no VLM):
semantic-search candidate photos to eyeball, `vlm_used:false`. Cache: per-photo result by file id.

### 4.8 `auto_biography_chapter(start_date, end_date)` — 🐢 demo-wow *(flagship)* **[M4/M7]**
Combines `moments/calendar` + `moments` + all `journals` + `for_you/items` over the range.
Data: structured chapter outline (ordered scenes, people/places, hero images captured durable
via the new generic `media_key`, throughline candidates). Enrichment: memoir narrative + VLM
hero captions. Degraded: the outline (Claude narrates in-client). Cache keyed on `(start,end)`.

### 4.9 `the_unwritten(days=14, min_significance=2)` — ⚡ demo-wow **[m2]**
`moments` (captured) vs `journals/by_date` (written) over a window. **[m2]** Uses
`_flatten_buckets`; a moment on day D counts as "written about" if D ∈ `[start_date, date]` of
any (incl. multi-day STORYBOARD/DAILY_ROUTINE) bucket — avoids false "unwritten" hits. Data:
significant captured-but-unwritten moments, heuristic significance (media count, duration,
distinct location). Enrichment: LLM significance ranking. Degraded: pure data diff.

### 4.10 `year_in_review(start_date, end_date)` — 🐢 demo-wow *(flagship)* **[NEW, S1]**
"Wrapped" for your life. **Built to be feasible:** primarily `moments/calendar` +
`journals/calendar` (one ranged call each over the window) + **one ranged** `for_you` call,
with *sampled* day-detail and DIETARY/place pulls rather than a full per-day scan — keeping it
within the governor budget. Data: top places (reusing 4.2's cover_file ranking), busiest days,
vlog/comic counts, nutrition highlights, distinct-people estimate. Cache keyed on `(start,end)`.
Enrichment: a shareable narrative recap. *(Swap candidate: `catch_me_up` if a snappy realtime
briefing is preferred.)*

---

## 5. Cross-Cutting Concerns

- **Registration / count:** +5 `register_*` in `server.py`; `TOOL_COUNT` 24 → 34; `/health`;
  update server `instructions` (incl. the envelope-split note [m1] and a privacy line [P1]).
- **Rate limiting [B2/C5]:** governor + `scan.py` budgets; `meta.capped` distinguishes
  `budget` vs `rate_limit`.
- **Caching [M2]:** resolved-window keys + TTL; in-process singleton fallback.
- **Errors:** reuse `client.format_error`; tools return `f"Error: {…}"`; enrichment failures
  swallowed (best-effort), recorded in `meta.enrichment_skipped_reason`.
- **Timezone:** reuse `convenience._today_local` / `_days_ago_local`.

## 6. Documentation, Config & Privacy

### 6.1 Privacy disclosure **[P1/P2]**
- README + `.env.example` + server `instructions` state prominently: **configuring an LLM/VLM
  provider sends your photos, journal text, locations, and the names of people in your life to
  that third-party API.** Default (`none`) keeps everything on-box.
- `LOOKI_LLM_API_KEY` is never logged or echoed in errors. Langfuse traces log metadata
  (lengths/counts), never image bytes or journal/OCR content.
- **[P3]** Treat VLM/OCR/journal text as untrusted (prompt-injection): firm system prompts,
  model output used as data only.
- Durable MinIO captures + cache objects hold personal data — document that the bucket must
  not be public-read; keys avoid embedding raw sensitive strings.

### 6.2 Other docs
- `.env.example`: `LOOKI_LLM_*` / `LOOKI_VLM_MODEL` block (Forge = one `openai_compatible`
  option; `FORGE_*` back-compat; degradation note).
- `README.md`: "Insight Tools" section (10 tools, provider config, degradation guarantee,
  privacy note); tool count 24 → 34.
- `docs/narrative/`: build narrative (existing style).
- Live-findings doc (like `journals_api_findings.md`): record validated assumptions —
  **how often `cover_file.location` is populated**, real YESTERDAY_RECAP heading strings,
  `max_photos` × VLM latency, whether each provider can server-side-fetch Looki URLs.

## 7. Testing

- Pure helpers off-network (`temporal`, `geo`, `journal_mine` over multi-variant fixtures
  **[B3]**, `scan` paging, `governor` token-bucket timing) per `scripts/test_journals_helpers.py`.
- `insight/llm.py`: mock httpx per provider shape (openai/anthropic/gemini); assert the
  **unconfigured path returns `None`, never raises** [C3], and that a failed structured call
  sets `enrichment_skipped_reason` [M5].
- **[A2]** Characterization test: `describe_realtime_event` output identical pre/post refactor
  when `FORGE_*` is set.
- Live smoke test extends `scripts/test_all_tools.py`: all 10 return a valid envelope **with
  and without** an LLM provider configured, and `meta.capped` behaves under a tight budget.

## 8. Out of Scope / Future

- Approach C precompute service (cron baselines/heatmaps in Postgres) — only if deep tools are
  too slow live.
- Media generation (rendered heatmaps, montages).
- Alternates not chosen (`catch_me_up`, `trace_a_thread`, `wellness_arc`).

## 9. Suggested Build Sequencing (ship in 2–3 PRs **[S2]**)

1. **PR1 — Insight core:** `governor.py`, `client.py` 429 backoff, `llm.py` (+ refactor
   `describe_realtime_event` onto it + envelope + char test), `envelope.py`, `scan.py`,
   `cache.py`, `storage.media_key`. Provider matrix + degradation tests first.
2. **PR2 — LLM-free wins:** `commitment_harvester`, `the_unwritten`, `places_of_my_life`
   (default mode), `journal_mine` + `geo` + `temporal` with fixtures.
3. **PR3 — Deep + vision:** `life_rhythm` → `what_was_different`, `on_this_day_rewind`,
   `auto_biography_chapter`, `year_in_review`, `people_and_meetings_intel`, `visual_search`
   (match + ocr). Docs + privacy + live smoke + narrative.
   - **PR3 prerequisite (from PR1 final review):** route `insight/llm.py`'s VLM/LLM HTTP calls through `insight/governor.py` before `caption_images`/`visual_search` are consumed, so combined Looki + VLM throughput respects the 60 req/min window.
