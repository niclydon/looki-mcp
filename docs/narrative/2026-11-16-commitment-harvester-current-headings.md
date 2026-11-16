# The Harvester Was Reading Last Season's Headings

The 2026-11-15 live smoke of the resurrected Insight tools (OB-69927)
asked `commitment_harvester` for one day and got 18 items from two
journal entries, every one marked `parsed_section: false`. The tool was
meant to return the follow-ups Looki writes into its recaps. It was
returning the whole recap instead.

## What had drifted

`journal_mine.extract_todo_section` matched a fixed set of headings
(Actionable Suggestions, TODOs, Action Items and a few variants) and,
when none matched, fell back to every bullet in the entry. A structure-only
read of the last 45 days of recap and audio-summary journals (heading
lines and line shapes counted, no content kept) showed why that fallback
now fired almost every time:

- YESTERDAY_RECAP ends in `### Suggestions for Today`, a numbered list.
  That heading was not in the set.
- AUDIO_SUMMARY and MANUAL_AUDIO_SUMMARY carry `### Key Takeaways` and
  `### Views`, which are narration, and only sometimes an
  `### Action items` (or `### Follow-ups`) section. Its dash bullets are
  often separated by one or two blank lines, and the old section reader
  stopped at the first blank, so even a recognised section lost items.

So recaps fell through to the fallback, and audio summaries without an
action section dumped their takeaways as if they were commitments.

## What changed

- The heading set gained `suggestions for today`, `suggestions` and
  `follow-ups`.
- A markdown (`#`) heading's section now runs to the next markdown
  heading, skipping blank and prose lines. A plain-text heading keeps the
  old blank-line rule, so older entries read the same.
- Several recognised sections in one entry all count, and the scan is
  single-pass: each section resumes where the last one stopped, so no line
  is read twice, and a list item such as `- Suggestions` is never taken
  for a heading.
- A `TODO` line needs a colon (bare or as a bullet), so prose that only
  starts with "TODOs" or "Todo list" is not a commitment.
- With no recognised section, explicit `TODO:` lines are still
  follow-ups. Every other bullet goes to `fallback_lines`, which the
  harvester counts (`unsectioned_line_count`, `unparsed_entry_ids`) but
  never returns as a commitment.
- The counters each mean one thing: `commitment_count` and `total` are
  the items returned, `entries_scanned` is everything the feed returned,
  `mined_entries` is the distinct recap and audio entries mined.

## How it was checked

Offline tests cover a current-format recap, an audio summary whose action
items are blank-separated, and one with no follow-up section; the three
fail on the old parser. Run over the last 14 days of mirrored journals on
Furnace (counts only), the new harvester returned 74 items, all from
recognised sections: 42 recap suggestions, 30 audio action items and 2
follow-ups. It left out 110 narration lines from 9 entries with no
follow-up section, and its counters agreed.

The first independent review found three ways narration could still leak
or double-count: colon-less "TODO" prose, a plain heading re-read inside a
markdown section, and a bullet that happened to read like a heading. Each
now has a regression test that fails on the earlier parser. Re-run after
those fixes, a day later in the window, the same check returned 76 items
from 37 entries, all from sections, with 110 narration lines left out.
