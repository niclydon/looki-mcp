# The Endpoint Retired While the Docs Stood Still

In July, Looki's endpoints stayed put and the contract drifted underneath them
(RP-57). In October the failure inverted: Looki retired `GET /for_you/items`
outright, which broke `get_highlights`, the one user-visible tool built on it,
while Looki's own published agent skill doc, byte-identical to the July
baseline, still documents the endpoint as live. The parity audit of
2026-10-16 turned that gap into ProjectManager track **RP-80**, three OBs, one
deployed code fix, and a contract record and probe harness re-baselined to the
API as it actually behaves today.

This is the record of that arc: the audit, the retirement and the smaller
drifts found beside it, the run-pack, the three slices (fix, docs, harness),
and the state of the service at close.

## The Setup: a Parity Audit, Not a Bug Report

The trigger was the periodic MCP API parity pass (the `local-mcp-api-parity`
workflow): inventory the tools looki-mcp ships against the live upstream API
and the upstream documentation, and report the gaps. Nobody had reported a
failure. The expectation, as in July, was a list of small contract drifts.

The audit ran on 2026-10-16 from furnace against the live Looki API:

| Fact | Value |
|---|---|
| API base | `https://open.looki.ai/api/v1` |
| Tools audited | **24** (the full looki-mcp toolset) |
| Probes | ~50 serial requests, inside the upstream **60 req/min** budget |
| Upstream skill doc | `https://web.looki.ai/agent/looki-memory/SKILL.md` |
| Skill doc sha256 | `4c5c991cb1165b910c6cd4d95ff20d4dc1f717678233a6a27a9d30421387f939` |
| OpenAPI surface | **None** (probed paths return 404, same as July) |

The first surprise was the hash. The skill doc's sha256 is **byte-identical**
to the 2026-07-18 RP-57 baseline
(`4c5c991cb1165b910c6cd4d95ff20d4dc1f717678233a6a27a9d30421387f939`).
Upstream had not revised a single byte of its published contract. The API
underneath it had changed anyway, which is the more dangerous kind of drift:
the documentation a new implementer would trust most is the documentation
that is now wrong, and nothing about its freshness signals that.

## What the Audit Found

### 1. `GET /for_you/items` is retired (the break)

The endpoint no longer degrades, misvalidates, or returns empty. It is gone,
and it says so:

```
HTTP 400, envelope code 105
"This endpoint is deprecated. Please use GET /journals instead."
```

`get_highlights` was the endpoint's only consumer in looki-mcp. Every call to
the tool therefore failed against the live API: this was the arc's one
user-visible break, and the only P0. It is worth recording that the tool did
not fail because of anything in this repo. The code matched the documented
contract; the contract's publisher retired the endpoint without updating the
document.

### 2. Moment payloads gained `search_context`

Moment payloads now carry a `search_context` field that neither the July
models nor the (unchanged) skill doc describe. Not breaking: additive fields
do not fail parsers. But an undocumented field on the primary payload type is
exactly the class of drift the probe harness exists to pin, and the models
now document it (OB-65517) and the probe asserts its shape (OB-65518).

### 3. The journal type vocabulary expanded, and `DAILY_VLOG` moved house

Four journal types observed live that the July record did not have:

- `DAILY_HEALTH_REPORT`
- `DAILY_VLOG`
- `MANUAL_AUDIO_SUMMARY`
- `PLOG`

`DAILY_VLOG` is the interesting one: in the July contract it was a
`/for_you/items` item type. It is now a **journal** type. That migration is
what makes the fix in OB-65516 possible at all: the content class that
`get_highlights` existed to surface did not disappear with its endpoint, it
moved to `/journals`, and upstream's own deprecation message names the new
home.

### 4. Two new error codes

The July vocabulary had envelope code `100` (invalid request parameters).
The October contract adds:

| Code | Meaning |
|---|---|
| `100` | Invalid request parameters |
| `105` | Deprecated endpoint |
| `106` | Missing auth token |

Code `106` is observable by calling `/me` with no key. Pinning the vocabulary
matters because the probe harness asserts on these codes: an unpinned harness
cannot distinguish "upstream changed the error contract" from "our request
was wrong."

### 5. Smaller contract nuances

- The journal `content` key is **present on text journal types and omitted
  on media types**. Consumers must treat absence as normal, not as an error
  or an empty body.
- The `/journals` `type` and `group` query parameters are **silently ignored
  upstream**. Filtering by them server-side does not work; anything that
  needs a type filter must filter client-side (this directly shaped the
  OB-65516 design).
- The observed `/me` key set was recorded into the contract docs so the next
  audit diffs against a written baseline instead of memory.

## From Audit to Run-Pack (RP-80)

The audit closed as a filed project track, at the operator's direction on
2026-10-16:

| Field | Value |
|---|---|
| Track | `looki-mcp-api-parity-2026-10` |
| Display | **RP-80** |
| Run-pack | `rp-2026-10-16-looki-api-parity` |
| OBs | **3** (65516–65518) |

| Pri | OB | Title |
|---|---|---|
| P0 | **OB-65516** | `get_highlights` broken by the `/for_you/items` retirement |
| P1 | **OB-65517** | Contract docs (`models.py`, `journals_api_findings.md`) predate the October contract |
| P1 | **OB-65518** | `api_contract_probe.py` baseline predates the retirement; failures mix signal with staleness |

The ordering was deliberate: fix first (a live tool was broken), then the
written contract, then the harness that guards the contract. The harness went
last so its new expectations could be written against the already-fixed
highlights behavior rather than a planned one.

## OB-65516: `get_highlights` Rebuilt on `/journals`

### Design

`get_highlights` was re-implemented in `looki_mcp/tools/highlights.py` as a
client-side composite over `GET /journals`, fetched through
`client.governed_get`:

- Filter to journal types `{DAILY_VLOG, COMIC_PAGE, PLOG}`, the journal-side
  successors of what `/for_you` surfaced as highlights.
- Newest first.
- **Bounded scan: at most 6 pages / 93 days.** Journals are per-day buckets
  and mostly not highlights; an unbounded scan for a `limit` of highlights
  could walk the entire journal history. The cap is stated in the tool
  description so callers know the window they are searching.
- Client-side filtering is not a preference here: finding 5 above records
  that the `/journals` `type`/`group` params are silently ignored upstream,
  so there is no server-side filter to call.

The `/for_you` call path and its validators were **deleted**, not left behind
a flag. A retired endpoint does not come back on a schedule anyone here
controls, and dead call paths are how the next implementer reintroduces the
break.

### Ship and verification

| Step | Evidence |
|---|---|
| PR | **#5**, squash merge `cf79a8cd1864178c6553d6997dbd7097c3e9e7b0` |
| New tests | `scripts/test_highlights.py` (fixture tests for the composite) |
| Offline suite | **14 of 15** `scripts/test_*.py` PASS; `test_all_tools.py` skipped (live harness) |
| Deploy | `scripts/deploy.sh` to `/services/looki-mcp`; `.deployed-sha` = `cf79a8cd1864178c6553d6997dbd7097c3e9e7b0`; health ok |

Live smoke through the MCP gateway, `get_highlights` with limit 5:

| Observation | Value |
|---|---|
| Items returned | **5** |
| Types | `COMIC_PAGE` ×3, `DAILY_VLOG` ×2 |
| Dates | 2026-10-15 / 2026-10-14 / 2026-10-13 |
| `source` | `"journals"` |
| `scanned_entries` | 250 |
| `has_more` | true |
| Deprecation error | **none** |

250 scanned entries for 5 highlights is the bounded scan working as designed:
the journal stream is dense, the highlight types are a minority of it, and
the tool reports how far it looked instead of pretending the window was the
whole history.

## OB-65517: The Contract Docs Tell the Truth Again

With the tool fixed, the written contract was refreshed to match October:

- `looki_mcp/models.py` and `journals_api_findings.md` re-stamped
  **"verified 2026-10-16"**.
- `/for_you/items` recorded as retired (HTTP 400, envelope code 105) rather
  than quietly removed, so a future reader knows it existed, died, and when
  that was confirmed.
- `search_context` documented on moment payloads.
- The four new journal types (`DAILY_HEALTH_REPORT`, `DAILY_VLOG`,
  `MANUAL_AUDIO_SUMMARY`, `PLOG`) added to the vocabulary.
- Error codes `100` / `105` / `106` documented with meanings.
- The `content`/`thumbnail` omission nuances (present on text types, omitted
  on media types) written down.
- The observed `/me` key set recorded as the diff baseline for the next audit.

PR **#6**, squash merge `b2b3d51796eeb0bc3e0d95a0fddeab22dc8419c1`.
Docs-only: no deploy, no service restart. Nothing about the running service
changed, and the merge record says so rather than implying a ship.

## OB-65518: The Probe Harness Stops Crying Wolf

`scripts/api_contract_probe.py` existed, since RP-57, so the next drift
would not need a full discovery session. By October its baseline *was* the
drift: it still expected `/for_you/items` to succeed, so it exited 1 with
failures that mixed the real regression with obsolete expectations. A harness
whose red is partly stale trains its readers to ignore red, which is worse
than no harness.

The re-baseline:

- `/for_you/items` removed from `KNOWN_PATHS` success expectations and now
  **asserted retired** (HTTP 400, envelope code 105). If upstream ever
  revives the endpoint or re-codes the refusal, the harness trips. That
  assertion is the early-warning tripwire for the next upstream change.
- Error-code vocabulary pinned: `100` invalid params, `105` deprecated
  endpoint, `106` missing auth token.
- A `search_context` shape check added on moment payloads.
- Journal type vocabulary refreshed to the October 2026 set
  (`DIARY`, `YESTERDAY_RECAP`, `AUDIO_SUMMARY`, `MANUAL_AUDIO_SUMMARY`,
  `COMIC_PAGE`, `DAILY_VLOG`, `DAILY_HEALTH_REPORT`, `PLOG`, plus prior
  types). Unknown future types are **warnings, not failures**: the vocabulary
  has expanded twice in three months, and a harness that fails on every
  upstream addition would be re-baselined into uselessness.
- The probe stays serial and paced, inside the 60 req/min budget.

Validated both ways, per the OB's acceptance criteria: green against the
live API, and a deliberately flipped expectation failed loudly (exit 1,
naming the mismatch) before being reverted. The green run, from
OB-65518's close evidence:

| Observation | Value |
|---|---|
| Exit code | **0** (`=== all live checks passed ===`) |
| Requests | **15** in **18.1s**, serial paced |
| Known paths | all 8, envelope code 0 |
| `/for_you/items` assertion | retired as expected (HTTP 400, code 105) |
| No-key `/me` | code 106 |
| `sort_order=ASC` | code 100 |

PR **#7**, squash merge `43f0a003475fe043a959805bc7825b528ea39bba`.
Script-only: no deploy, no service restart.

## Alternatives Rejected

| Idea | Why not |
|---|---|
| Point `get_highlights` at another upstream highlights endpoint | None exists. Upstream's own deprecation message names `GET /journals` as the successor |
| Keep the `/for_you` path behind a fallback flag | Dead code calling a retired endpoint; the next implementer inherits the break |
| Unbounded journal scan for highlights | Journals are dense per-day buckets; an unbounded scan trades a correctness edge case for unbounded latency and rate budget |
| Server-side type filter on `/journals` | The `type`/`group` params are silently ignored upstream; the filter would silently not filter |
| Delete the probe's `/for_you` checks with no replacement (OB-65518 Option B) | The deprecation assertion is the tripwire; deleting it removes the early warning |
| Fail the probe on unknown journal types | The vocabulary expanded in July and again in October; warn-only keeps the harness readable as signal |
| Redeploy for the OB-65517 / OB-65518 merges | No runtime code changed after `cf79a8c`; a redeploy would stamp a new SHA for zero behavioral change |

## Numbers Worth Keeping

| Observation | Value |
|---|---|
| Tools audited | **24** |
| Tools broken at audit | **1** (`get_highlights`) |
| Tools healthy at close | **24** |
| Audit probes | ~50 serial, inside 60 req/min |
| Skill doc sha256 | `4c5c991cb1165b910c6cd4d95ff20d4dc1f717678233a6a27a9d30421387f939` (unchanged since 2026-07-18) |
| Retired endpoint error | HTTP 400, code 105, "This endpoint is deprecated. Please use GET /journals instead." |
| Highlights smoke | 5 items, `scanned_entries` 250, `has_more` true |
| Probe green run | exit 0, 15 requests, 18.1s |
| OB-65516 merge | `cf79a8cd1864178c6553d6997dbd7097c3e9e7b0` (PR #5) |
| OB-65517 merge | `b2b3d51796eeb0bc3e0d95a0fddeab22dc8419c1` (PR #6) |
| OB-65518 merge | `43f0a003475fe043a959805bc7825b528ea39bba` (PR #7) |
| Deployed service SHA at close | `cf79a8c` (the only code change of the arc) |

## State at Close

**Unblocked**

- `get_highlights` works again, on the endpoint upstream itself named as
  the successor, and is deployed (`.deployed-sha` = `cf79a8c`, health ok).
- All 24 tools are healthy against the live October 2026 contract.
- The written contract (`models.py`, `journals_api_findings.md`) is stamped
  verified 2026-10-16 and records the retirement, the new field, the new
  types, and the new error codes.
- The probe harness's red once again means signal: its baseline is the
  current contract, including an assertion that fires if the retired
  endpoint's status changes.

**Pending (outside this arc)**

- Upstream's own skill doc still documents `/for_you/items` as a live
  endpoint. That is Looki's documentation lag, outside this repo's control;
  it is recorded here and in the contract docs so nobody re-derives the
  break from the official doc. The probe's skill-hash baseline will show
  when upstream next revises the doc, and the next parity pass should diff
  the revision against this record.
- The deployed service remains at `cf79a8c`. The OB-65517 and OB-65518
  merges (docs and probe script) do not redeploy, by design.

See `CHANGES.md` entry **2026-10-16 — Looki API parity (RP-80)** for the
chronological pointer.

> Executed by Muse narrative-docs worker (model: Muse Wonder), 2026-10-16.
