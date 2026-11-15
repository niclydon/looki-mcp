# The Three Insight Tools Came Back, and One of Them Mines Less Than Its Name Says

In July, RP-57 built three composite "Insight" tools on top of the raw
Looki API: `commitment_harvester`, `the_unwritten`, and
`places_of_my_life`. They never merged. The branch was archived as
`archive/feat-insight-tools-pr2` (tip `f2f6b8e`) while the server's
contract work took priority, and the tool count stayed at 30. On
2026-11-10 the looki-mcp upgrades scan (walk item 7, approved by the
operator) put them back on the list as track RP-117, split into an
implementation OB (OB-69926) and this documentary closeout (OB-69927).

## Why they came back

The July shelving was not a judgement on the tools. It was a judgement
on the ground they stood on. By November that ground had moved
twice. `GET /journals/by_date`, which `the_unwritten` relied on, was
retired upstream, and the 2026-11-09 contract work (RP-115) had pinned
down which journal types actually carry text. The moment-file cursor
fix (OB-69849) had also landed. A port onto current main was now a
reconciliation job, not a rewrite.

## What the port changed

PR #43 (merged as `4c62eca`, 2026-11-13) ported the archive file by
file instead of merging it:

- `the_unwritten` reads the paged `GET /journals` feed through
  `insight.scan.walk_journals`, and counts a day as written only for
  event-level entries (`DIARY`, `AUDIO_SUMMARY`,
  `MANUAL_AUDIO_SUMMARY`, `STORYBOARD`), not media-only types.
- `places_of_my_life` uses main's `insight.geo`, so JSON address
  strings collapse to a locality label, and drops the archived `deep`
  flag, which did nothing.
- `commitment_harvester` mines `YESTERDAY_RECAP`, `AUDIO_SUMMARY` and
  `MANUAL_AUDIO_SUMMARY`, the text types the November contract
  confirmed.
- All three return the `{data, narrative, meta}` envelope, with
  `narrative` null when no LLM provider is configured. Nothing is
  truncated.
- `TOOL_COUNT` went from 30 to 33, and the README tool table and
  `CHANGES.md` were updated in the same PR, so this closeout did not
  need to touch either.

## Re-verification, live

The deploy (`scripts/deploy.sh`) put `4c62eca` into
`/services/looki-mcp`; the service has been up since
2026-11-13 14:37 UTC, and `GET /health` on Furnace answered
`{"status":"ok","server":"looki-mcp","version":"1.1.0","tools":33}` on
2026-11-15. Each tool was then called against the operator's own
account on 2026-11-15 (about 04:55 UTC). Only shapes and counts are
recorded here; the content is the operator's own life and stays out of
the repo.

| Tool | Arguments | Result |
|---|---|---|
| `places_of_my_life` | `days=3`, `top_n=3` | 3 places returned of 4 distinct, 58 moments, `unknown_count` 0; each place has `visits`, `total_seconds` and a `sample_moment`; meta `calls_used` 4, `days_scanned` 4 |
| `the_unwritten` | `days=2`, `min_significance=4` | `unwritten` empty: all 46 moments fall on 4 dates that already have an event-level entry; `covering_types` lists the four event types; meta `days_scanned` 3 |
| `commitment_harvester` | `days=1` | 18 items from 2 mined entries (one `AUDIO_SUMMARY`, one `YESTERDAY_RECAP`), every item `parsed_section: false`; `unparsed_entries` 2 |

All three came back with `narrative: null`, `cache_hit: false` and
`vlm_used: false`, as expected on a server with no LLM provider.

## The finding: the harvester's fallback is doing all the work

`places_of_my_life` and `the_unwritten` behaved as designed. The
empty `unwritten` list is the honest answer for a two-day window where
every day already has a diary or audio summary.

`commitment_harvester` is the one to watch. Every one of the 18 items
it returned came through the extractor's fallback path
(`parsed_section: false`): neither entry had an "Actionable
Suggestions" or "TODO" section the parser recognised, so the extractor
returned every bullet line in both entries. Most of those lines are
recap narration, not commitments. Only the last few bullets of the
recap read like follow-ups. The tool is not wrong about what it read,
and it truncates nothing, but its name promises a to-do list and on
current journal formats it hands back the whole entry instead. The
counters also disagree in a way a caller could trip on:
`commitment_count` is 18, `total` is 6, and `mined_entries` and
`unparsed_entries` are both 2.

That is filed as its own follow-up rather than fixed here, since this
OB is documentary: the section headings Looki writes now need to be
checked against `insight/journal_mine.py`'s patterns, and the fallback
should either be labelled clearly or stop presenting narration as
commitments.

## Not done here

- The local-looki Muse skill doc still describes the 30-tool surface.
  It is a separate surface and needs its own refresh to 33 tools; this
  OB only flags it.
- PR #38 (dependency lock, OB-69924) merged after the `4c62eca` deploy
  and is not yet live.

See `CHANGES.md` (2026-11-15 entry) for the chronological summary, and
the 2026-11-12 entry for the port itself.
