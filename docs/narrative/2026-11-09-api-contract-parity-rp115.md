# The Second Endpoint Retired, and a Field Nobody Had Captured

Looki's journal date endpoint had been a documented part of the Open API since
the journals family landed in June, and `looki-mcp` built two everyday tools on
it, `get_journals_by_date` and `get_todays_journal`, which broke when Looki
retired `GET /journals/by_date` outright, so the November parity pass re-based
both tools on the paged `GET /journals` feed, captured a per-moment field the
repo had never carried at all, and re-baselined the written contract and the
probe harness to the API as it actually behaved on 2026-11-09.

That arc ran as ProjectManager track **RP-115**
(`looki-mcp-api-parity-2026-11`), four backlog items, four pull requests, two
deployed code changes, one docs refresh, and one harness re-baseline. The pack
itself closed on 2026-11-09. What it did not leave behind, at close, was its
narrative. This document is that record, written after the fact from the probe
evidence, the close evidence on the four items, and the merged diffs, so the
arc is reconstructible from the repo alone rather than from chat history.

## The Setup: a Direct-API Probe, Not the MCP

### Why the probe bypassed looki-mcp

The trigger was a question about always-on recording. Nic's Looki device had
gained an always-on audio mode, and the question was whether that mode had
changed what the Open API exposes: new endpoints, new fields, a transcript
surface, a stream, anything structural. Answering that through `looki-mcp`
would have answered a different question, because the MCP can only show what
its own tool shapes already carry. A field the repo never modelled is
invisible through the repo's own tools.

So the discovery pass on the morning of 2026-11-09 called the Looki Open API
directly.

| Fact | Value |
|---|---|
| API base | `https://open.looki.ai/api/v1` |
| Auth | `X-API-Key` header only |
| Key handling | Resolved on Furnace in-process from the service environment, never printed, never moved |
| Probe volume | ~130 serial live calls |
| Rate result | Zero 429 responses |
| Baseline | The repo's `models.py` and findings, last verified 2026-10-16 (RP-80) |
| Envelope | `{code, detail, data}` |

The serial pace was deliberate: the October audit had established the
upstream budget at 60 requests per minute, and a probe that trips the rate
limiter produces evidence about the limiter rather than about the contract.

### The baseline problem

RP-80, a month earlier, had left the repo in a good position for this pass:
the written contract was stamped verified 2026-10-16, the error vocabulary
was pinned, and the probe harness asserted the `/for_you/items` retirement
so a second retirement would show up as a pattern rather than a surprise.
The November probe diffed the live API against that written baseline, not
against memory and not against upstream's published skill document. That
choice mattered, because upstream's document had already proved unreliable
in October, and by November it was worse than unreliable. It was gone.

## What the Probe Found

### 1. `GET /journals/by_date` is retired (the break)

The endpoint returns the standard deprecation envelope:

```text
HTTP 400, envelope code 105
"use GET /journals instead"
```

Code 105 is the same code RP-80 pinned for the `/for_you/items` retirement,
so the refusal shape was familiar. The blast radius was not. Two tools were
built on the retired path:

- `get_journals_by_date`, the direct mirror of the endpoint.
- `get_todays_journal`, the convenience composite that resolved "today" in
  the account timezone and then called the same endpoint.

Every call to either tool therefore failed against the live API. As in
October, the tools did not fail because of anything in this repo. The code
matched the contract as last verified; the publisher retired the endpoint
in the intervening month.

`GET /for_you/items`, retired in October, was re-checked and remains
retired on the same contract, HTTP 400, code 105. Two retirements in two
consecutive parity passes is the pattern the probe harness now exists to
catch early.

### 2. `audio_summary`: a long-standing field the repo never captured

The largest finding was not a retirement. It was a field.

Moment payloads carry `audio_summary`, a per-moment text summary of heard
speech. It appeared nowhere in the looki-mcp repo: not in the models, not in
any tool's output shape, not in the findings documents, and not in the Nexus
ingest projection examined later in the arc. A caller using only the estate's
own tools would have no way to know the field existed.

The probe sampled days from 2026-09-15 through 2026-11-09, and the field was
present on every sampled day. It was non-empty on between 43 percent and 93
percent of moments depending on the day. Two facts follow from that sampling,
and both are recorded here because they correct the framing the arc started
with:

- `audio_summary` predates always-on recording. It was not introduced by
  the always-on mode, whatever that mode changed about capture behaviour.
- An always-on density boost, more speech captured per day and therefore
  richer summaries, is plausible but unverified from the API evidence. The
  probe recorded the correlation question and did not assert it as a cause.

The field carries two value forms, and any consumer has to handle both:

| Form | Shape |
|---|---|
| Prose string | A plain narrative summary of the heard speech |
| JSON string with topics | A serialized JSON string whose payload includes a topics list alongside the text |

Observed lengths on the recheck day ran from 81 characters to 1,465
characters. The JSON-string form was observed on a pure-AUDIO moment, which
is the moment class where the distinction matters most: a consumer that
assumes plain prose will render serialized JSON to its reader, and a
consumer that assumes JSON will fail on the majority form.

### 3. Always-on recording added no structural API surface

The question that opened the arc got a clean negative answer. The probe
tried 24 candidate paths for the surfaces always-on recording might plausibly
have added:

- audio collection and item routes,
- transcript routes,
- segment routes,
- recording and continuous-capture routes,
- realtime audio and realtime stream routes.

All 24 returned a bare 404. No new endpoints, no new fields beyond the
already-present `audio_summary`, no new enums, and no new media kinds were
found. Raw continuous audio is not exposed on this surface. Neither is a
transcript, a segment list, or a stream.

Two apparent exceptions during probing resolved as traps rather than
discoveries, and both are recorded in the contract docs because the next
implementer will hit them:

- `/moments/audio` and `/moments/transcripts` return 422, not 404. That is
  the `/moments/{id}` route rejecting a non-UUID path segment, verified by
  control calls. It is not evidence of an audio sub-resource.
- Any `/moments/{id}` call with a non-UUID identifier returns HTTP 422,
  envelope code 100. Path probing against this API must use UUID-shaped
  candidates or accept that 422 means "not a route" as often as it means
  "bad parameters."

### 4. Minor drift, recorded because drift compounds

None of the following broke a tool on 2026-11-09. All of them were written
into the contract record anyway, because the October pass had shown that
today's cosmetic drift is next month's broken assumption.

| Surface | October baseline | November observation |
|---|---|---|
| Moment-files pagination key | `next_cursor_id` | `next_cursor` |
| Presigned file host | `devo-user-file.looki.ai` | `user-file.looki.ai` |
| `search_context` | Undocumented field, shape unknown | A comma-separated keyword string, 34 to 123 characters, not an object |
| `/me` key set | Recorded October set | Unchanged; the `-05:00` timezone offset is seasonal |
| Journals | 511 entries across 31 days in the October window | Same nine journal types, including `AUDIO_SUMMARY`, at six to eight entries per day |
| Realtime | Latest-event snapshot | Still snapshot only; no list, history, or stream route |
| Error vocabulary | 100 invalid params, 105 deprecated, 106 missing auth | Unchanged |
| `/journals` `sort_order` | Lowercase only | Still lowercase only; uppercase returns code 100 |

One item in that table outlived the probe as an open defect rather than a
doc note. `walk_files` in this repo still reads the retired pagination key
`next_cursor_id`. The rename was verified live, the docs now state it, and
the runtime gap was filed separately as **OB-69849**. It was deliberately
not fixed inside the docs item that surfaced it; see the side-finding
section below.

### 5. The upstream skill document is dead

In October, upstream's agent skill document at
`https://web.looki.ai/agent/looki-memory/SKILL.md` was byte-identical to the
July baseline and still documented a retired endpoint as live. In November
the same URL returns 404.

That changed the probe harness's behaviour in a way nobody had designed
for. `scripts/api_contract_probe.py` fetched the skill document as a
baseline step and hard-failed when the fetch failed, which meant the harness
could no longer reach its own live checks at all. A dead documentation URL
had become a harness outage. OB-69847's re-baseline therefore included one
supporting fix beyond its original scope: a failed skill fetch now warns
and lets the live contract decide the result. The harness judges the API,
not the documentation about the API.

No OpenAPI or docs routes exist on the API base itself. There is no
upstream machine-readable contract to fall back to, which is precisely why
this repo keeps its own written one.

## The Today-Only Recheck

Nic challenged the morning report the same day, at 13:16 ET, with the
obvious question: was there really nothing from the API that day with audio
summaries or any audio content at all. The morning probe had sampled today early, when the device day was only
six moments old, so a claim about "today" warranted an exhaustive re-run.

So the recheck covered 2026-11-09 only, America/New_York, direct API:
every moment, every file, every journal entry, and the realtime event.

| Check | Result |
|---|---|
| Moments today | 9 (the day had grown from 6 since the morning probe) |
| Moments with non-empty `audio_summary` | 8 of 9 |
| Moments with the key absent entirely | 1 |
| Moments with an empty or null value | 0 |
| `audio_summary` lengths | 121 to 1,465 characters, prose form |
| Files across all 9 moments | 89, all IMAGE; 0 AUDIO, 0 VIDEO |
| Journal entries today | 6, including 2 `AUDIO_SUMMARY` entries with full content (5,506 and 2,208 characters) |
| Realtime latest event | Image only, no audio-adjacent fields |

The recheck refined the morning numbers without overturning them. Audio
summaries as text were present that day, on nearly every moment, despite
there being no audio media at all in the day's files. The API gives the
estate Looki's written summaries of what the device heard, not the audio
itself. The one dedicated AUDIO media file in the wider sample belonged to
2026-11-06, a single file of 917,248 milliseconds, roughly 15.3 minutes.
AUDIO as a media kind predates always-on.

## From Probe to Run-Pack (RP-115)

The probe report was delivered in the main chat on 2026-11-09, and Nic
directed the filing the same day: file the parity run-pack, fix the retired
endpoint, capture `audio_summary`. The filing followed the October RP-80
mechanics, scripts copied from the proven October pair and edited, because
a filing pattern that has already produced a clean track and linked items
is worth more than a fresh improvisation.

| Field | Value |
|---|---|
| Track | `looki-mcp-api-parity-2026-11` |
| Display | **RP-115** |
| Track id | `f3282627-31f1-400a-aa8f-830fae252f0b` |
| Kind | repo_project, active, priority 2 |
| Owner | project-worker |
| Discovery date | 2026-11-09 |
| Prior track | `looki-mcp-api-parity-2026-10` (RP-80) |

| Pri | OB | Work type | Title |
|---|---|---|---|
| P0, priority 85 | **OB-69844** | fix | `get_journals_by_date` and `get_todays_journal` broken by the `/journals/by_date` retirement |
| P1, priority 70 | **OB-69845** | feature | Capture `audio_summary` in the moment tools, and assess Nexus ingest |
| P2, priority 55 | **OB-69846** | docs | Refresh the contract docs to the 2026-11-09 verified state |
| P2, priority 55 | **OB-69847** | automation | Re-baseline `api_contract_probe.py` to the 2026-11-09 contract |

All four items were filed with source manual, category
`looki-mcp/api-contract`, status triaged, the `autonomous_safe` delegation
tag, surface `mcp`, and suggested agent project-worker, and linked to the
track with relationship `advances`. The ordering constraint was stated at filing and honoured at execution:
OB-69847, the harness, lands after OB-69844, the fix, so its new
expectations are written against working journal tools rather than planned
ones. The pack was filed and presented, explicitly not auto-started. Nic's
go came later the same day, at about 14:03 ET, in the main chat: walk the
run-pack through the PMO and get it done now.

## Execution: the Pack Drains in One Afternoon

### Provenance: staged pull requests and a stalled lane

The execution did not start from a blank tree. A prior Codex lane had
already implemented three of the four items and staged pull requests #15,
#16, and #17, and had then stalled on review gates. The code existed; the
landings did not.

The ProjectWorker runner that took the pack,
`muse:projectworker:20261109-1405-rp115`, claimed the pack at 14:05 ET and
made the provenance decision explicitly: independently re-verify each
staged artifact, diff review, full test re-runs, live smokes, and carry the
verified work through merge, deploy, and close, rather than re-implementing
work that was already written. Re-implementation would have cost a second
implementation to gain nothing over verification of the first.

Two closes, OB-69844 and OB-69846, used adversarial-review waivers: the
reviews of the staged heads were never verdicted, and in OB-69846's case
the recorded approval bound a pre-merge head that a necessary merge of
current main superseded. Each waiver carries the runner's independent
re-verification as evidence in place of the missing verdict, and records
that this is a weaker gate than a verdicted review.

OB-69845 also fell outside the initial pack claim set; a truncated claim
response had hidden a skip. It was claimed separately in exact mode and
verified completed like the other three. Four items were requested, four
shipped, none blocked, none skipped as ineligible.

### OB-69844: the journal tools re-based on the feed

`get_journals_by_date` and `get_todays_journal` were re-implemented over
`GET /journals`, client-side, following the pattern RP-80 established for
`get_highlights`:

- Fetch the journal feed through `client.governed_get`, the governed client
  path with its rate discipline.
- Bound the scan at six pages of 31 days each.
- Select the requested calendar date client-side, because the feed's own
  filter parameters are not trustworthy, as RP-80 had already established
  for `type` and `group`.
- Keep the tool names, arguments, and timezone behaviour stable. Callers
  did not change; the implementation underneath them did.
- Leave exactly one reference to the retired path in the runtime: a dated
  retirement comment. The call path was deleted, not flagged off.

| Step | Evidence |
|---|---|
| PR | **#16**, squash merge `aee1e6e48962c56ac87d6c19d01dfcd354811178` |
| Tests | 15 of 15 offline scripts pass, including new `test_journals_by_date.py` (date present, multi-page, absent, bounded scan) |
| Deploy | `scripts/deploy.sh origin/main` to `/services/looki-mcp`, health ok |
| Live smoke, by date | `get_journals_by_date` for 2026-11-08 returned 8 entries, no error |
| Live smoke, today | `get_todays_journal` returned 8 entries for 2026-11-09, timezone America/New_York, no error |
| Live smoke, absent date | 2020-01-01 returned empty with `scan_capped=true`, no error |

The absent-date behaviour is worth its line. A bounded scan cannot prove a
date has no journals; it can only report that it looked to its bound and
found none, and say that it was capped. The tool reports `scan_capped`
rather than asserting an empty history it did not read.

### OB-69845: `audio_summary` captured, and the ingest question answered

The feature half added a normalizer, `looki_mcp/audio_summary.py`, that
accepts both observed value forms and emits one shape:

```text
{text, topics, truncated}
```

Summary-mode surfaces cap the text at 600 characters and topics at 20, in
line with the repo's established summary and detail token discipline: list
and calendar views stay cheap, detail views return the full value. The
field was surfaced in every moment-returning tool the item briefed, not
only the detail tool, because a field visible only in detail views would
repeat the original invisibility in a milder form.

| Step | Evidence |
|---|---|
| PR | **#17**, squash merge `e39913ba5d0c00373d1bcdc162d659e78768bab6` |
| Merge work | A `CHANGES.md` conflict against the OB-69844 merge was resolved by the runner |
| Tests | 16 of 16 offline tests pass on the merged tree |
| Deploy | `scripts/deploy.sh`, health ok |
| Live smoke | `get_moments_by_date` for 2026-11-09 returned 11 moments, 10 with normalized `audio_summary`; the one without matches the key-absent moment from the recheck |
| Detail smoke | `get_moment_details` returned full text with `truncated=false` |

The assessment half was scoped as assessment only, and it produced the
arc's most consequential finding after the field itself. The question was
whether Nexus ingest already stores `audio_summary`. The answer splits at
the raw and silver boundary:

| Layer | Table | Finding |
|---|---|---|
| Raw ingest | `aurora_raw_looki_moments` | Already captures the field. Non-empty `audio_summary` in 193 of 3,947 rows, all within the most recent 353 ingested |
| Silver projection | `aurora_silver_looki_moments` | Drops it. No `audio_summary` column, and 0 of 3,947 payloads carry the key |

So the data was arriving and being stored, and then being discarded by the
projection that downstream consumers actually read. No ingest code changed
inside OB-69845; that was the item's fence and it held. The finding went
into the close evidence and became a linked follow-on, **OB-69851**,
"Preserve Looki moment audio_summary in the Nexus silver projection,"
linked to the RP-115 track with relationship `advances`. OB-69851 was
filed, not started. It belongs to the Nexus ingest surface, not to this
repo, and bundling it into a looki-mcp feature item would have crossed the
repo boundary the pack was organised around.

### OB-69846: the written contract tells the November truth

The docs item refreshed `looki_mcp/models.py` and the findings record to
the verified 2026-11-09 state:

- `/journals/by_date` recorded as retired, with the 400 and code 105
  refusal, rather than quietly deleted from the contract.
- `audio_summary` documented, in the normalized shape OB-69845 actually
  landed, `{text, topics, truncated}`. The staged draft had described it
  as a raw pass-through tracked separately; the runner merged current main
  into the branch, resolved the `models.py` overlap with OB-69845, and
  corrected the description to the shipped reality before merging. A docs
  item that documents the plan instead of the landing is a future parity
  pass's false baseline.
- The pagination rename, `next_cursor_id` to `next_cursor`, recorded.
- The presigned host rename, to `user-file.looki.ai`, recorded.
- `search_context` characterised as a comma-separated keyword string.
- The `/moments/{id}` non-UUID 422 trap recorded.
- The upstream skill document's death, 404 as of this pass, recorded.
- A stale findings note that still described OB-69844 as pending was
  corrected to its landed state.

PR **#15**, squash merge `d1b6f5ac09bb71876500ca1b513ef6443d78769c`.
Docs-only: no deploy, no service restart.

### OB-69847: the probe harness re-baselined, after the fix

The harness item landed last, as the ordering constraint required, and
changed `scripts/api_contract_probe.py` only:

- `/journals/by_date` removed from the success paths and now asserted
  retired, HTTP 400, code 105, alongside the existing `/for_you/items`
  assertion. Two retirement tripwires now stand where one stood.
- `audio_summary` and `search_context` shape checks added, sampled on a
  recent day, because a July sample would predate the field and a harness
  that samples stale fixtures asserts a contract nobody serves.
- The moment-files pagination expectation updated to `next_cursor`.
- The skill-document fetch failure downgraded from hard failure to
  warning, per the finding above, so the live checks are reachable again.

Validation ran both directions, as the October harness item had
established as the acceptance shape for this script. Against the live API
the probe exits 0, on the branch and again on merged main, 16 serial paced
requests, all sections OK. With one expectation deliberately flipped, the
probe exited 1 with loud failures on both retired paths; the flip was then
reverted. A harness that has never been seen to fail is not evidence of
anything.

PR **#18**, squash merge `42ca23fbfce3a2d5588ca7d6a2f70d612b93fa40`.
Script-only: no deploy, no service restart.

## Side Finding: OB-69849 and the Cursor the Docs Caught

The docs item's grep discipline produced a finding outside its own scope.
The contract record now states, in writing, that `walk_files` still reads
the old `next_cursor_id` key while the live API serves `next_cursor`. The
gap had already been filed as **OB-69849**, status new at pack close, and
the docs item did not fix runtime code inside a documentation change. That
restraint is the same one that kept the silver-projection fix out of
OB-69845: a pack stays auditable when each item changes what its title
says it changes.

## Alternatives Rejected

| Idea | Why not |
|---|---|
| Answer the always-on question through looki-mcp's own tools | The MCP shows only what its shapes carry; an unmodelled field is invisible through it. The probe had to go to the API directly |
| Point the journal date tools at another upstream date endpoint | None exists. Upstream's own deprecation message names `GET /journals` as the successor |
| Keep the `/journals/by_date` call behind a fallback flag | Dead code on a retired endpoint, the same reasoning RP-80 applied to `/for_you` |
| Unbounded feed scan for a requested date | The feed is dense per-day buckets; the bounded scan plus an honest `scan_capped` flag beats an unbounded walk of the full history |
| Pass `audio_summary` through raw in the moment tools | Two upstream value forms, one of them a serialized JSON string; raw pass-through pushes parsing onto every consumer |
| Fix Nexus ingest inside OB-69845 | Assessment-only was the item's fence, and the fix belongs to the Nexus surface; it was filed as OB-69851 instead |
| Fix `walk_files` inside the docs item | A docs change that also changes runtime pagination behaviour is neither; the gap was filed as OB-69849 |
| Re-implement the three staged PRs from scratch | The staged work verified clean under independent re-verification; re-implementation buys nothing over verification |
| Leave the probe's skill fetch as a hard failure | The dead upstream URL made exit 0 unreachable before any live check ran; the harness must judge the API, not its documentation |
| Redeploy for the docs and probe merges | No runtime code changed after `e39913b`; the deployed service already runs the pack's code |

## Numbers Worth Keeping

| Observation | Value |
|---|---|
| Probe calls | ~130 serial, zero 429s |
| Candidate always-on paths tried | 24, all bare 404 |
| Days sampled for `audio_summary` | 2026-09-15 to 2026-11-09, present on every sampled day |
| `audio_summary` non-empty share | 43 to 93 percent of moments, by day |
| Recheck day moments | 9, of which 8 with non-empty `audio_summary` |
| Recheck day files | 89, all IMAGE |
| Retired endpoints asserted by the probe | 2 (`/journals/by_date`, `/for_you/items`), both HTTP 400, code 105 |
| OB-69844 merge | `aee1e6e48962c56ac87d6c19d01dfcd354811178` (PR #16) |
| OB-69845 merge | `e39913ba5d0c00373d1bcdc162d659e78768bab6` (PR #17) |
| OB-69846 merge | `d1b6f5ac09bb71876500ca1b513ef6443d78769c` (PR #15) |
| OB-69847 merge | `42ca23fbfce3a2d5588ca7d6a2f70d612b93fa40` (PR #18) |
| Raw ingest rows with non-empty `audio_summary` | 193 of 3,947, all in the most recent 353 |
| Silver rows carrying `audio_summary` | 0 of 3,947 |
| Probe green run | Exit 0 against the live API, branch and merged main, 16 requests, all sections OK |
| Pack outcome | 4 requested, 4 shipped, 0 blocked, 0 skipped |
| Deployed service at pack close | `e39913b` (the pack's last runtime change) |

## State at Close, and Why This Ship Exists

**Closed by the pack**

- Both journal date tools work again, on the endpoint upstream named as
  the successor, deployed and smoke-verified live.
- `audio_summary` is a first-class, normalized field across the moment
  tools, deployed and smoke-verified live, in both of its upstream forms.
- The written contract is stamped to the 2026-11-09 verified state.
- The probe harness's baseline is the current contract, with two
  retirement tripwires, and its red has been demonstrated to still mean
  failure.

**Open, outside the pack, neither auto-started**

- **OB-69851**: preserve `audio_summary` in the Nexus silver projection.
  The data arrives; the projection discards it. Filed and linked to the
  RP-115 track.
- **OB-69849**: `walk_files` still reads `next_cursor_id`. Filed from the
  docs item's side finding; competing fixes are in flight on other lanes.

**Why a separate docs ship was needed at all**

The pack closed all four items done, with merges, deploys, and smokes on
record, and the repo's `CHANGES.md` carried entries for the two code items,
OB-69844 and OB-69845, written alongside their work. What it did not carry was any entry for the docs item or the harness
item, and the repo had no narrative for the arc. The record of a parity
pass is half of its value: the next pass diffs against the written
baseline, and a pass that ships code without writing its baseline down
leaves the next auditor diffing against chat history and close evidence
scattered across four backlog items. This ship closes that gap and
nothing else. It changes no runtime code, redeploys nothing, and restarts
nothing; the running service already carries the pack's code at `e39913b`.

See `CHANGES.md` for the chronological diff summary.

> Executed by Muse ship worker (model: Muse Wonder), 2026-11-09.
