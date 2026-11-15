# The Vendor Shipped an Official Stack, and the API Key Already Knew More Than It Said

*2026-11-10, looki-mcp, official-parity pass RP-116*

looki-mcp had been the estate's only Looki integration for five
months, built against the vendor's Open API by direct probing, when
Looki shipped an official access stack of its own (a plugin bundle
for eight AI clients, a skills repo, a hosted OAuth MCP server, and
an npm CLI) whose skill described record types this server had never
wrapped, so the parity pass read the official stack file by file,
probed what it pointed at, and closed the gap on the API-key surface
the estate already held: six tools added, 24 to 30, with the
contracts they run against verified live rather than taken from the
vendor's prose.

That work ran as ProjectManager track **RP-116**
(`looki-mcp-official-parity-2026-11`), eight backlog items,
OB-69894 through OB-69901, seven pull requests, one deployment. Its
downstream half, what Nexus did with the four record types once
they were reachable, is recorded in the nexus repo's narrative
`docs/narrative/2026-11-10-looki-ingest-medallion-rp116.md`. This
document is the looki-mcp half: the discovery, the wall the hosted
server puts in front of its own tool list, the CLI command table
that turned out to be the correct probe generator, the four
endpoints, the traps around them, and the options that were
considered and rejected with their reasons.

## Where the server stood

The baseline was strong, and the RP-115 record (the narrative
beside this one, `2026-11-09-api-contract-parity-rp115.md`) is the
reason. One day earlier the pack had re-based the journal date
tools on the paged `GET /journals` feed after the vendor retired
`GET /journals/by_date`, captured the per-moment `audio_summary`
field, refreshed the contract docs, and re-baselined the probe
harness. Main sat at `58bc63a`, the service ran 24 tools, and the
written contract in `models.py` had been verified against the live
API on 2026-10-16 and again, for the journal family, on 2026-11-09.

The auth shape matters for everything that follows. The server is
self-hosted FastMCP on Furnace, loopback port 7861, deployed at
`/services/looki-mcp` under the systemd unit `looki-mcp`, and it
authenticates to `https://open.looki.ai/api/v1` with a static API
key in the `X-API-Key` header. The key lives in the service
environment on Furnace and is resolved in process there; it is
never printed, moved, or committed. That shape (one server-side
credential, no per-client login) is what the official stack does
not offer, and it is why the parity question was never "migrate or
not" but "what has the vendor added that this surface can reach".

## The official stack, inventoried

The GitHub organization `looki-ai` carries exactly two public
repositories. There is no official SDK repo, no app repo, no
firmware repo, and no API-spec repo; that was verified directly,
not inferred from search results.

| Artifact | Facts |
|---|---|
| `looki-ai/looki-plugin` | Created 2026-09-16; v1.0.3 dated 2026-11-04; plugin manifests for Claude Code, Cursor, Codex, GitHub Copilot, Gemini, VS Code, Kimi, Grok. Every MCP config is identical: the hosted server at `https://open.looki.ai/mcp` |
| `looki-ai/looki-skills` | Created 2026-09-21; the single skill `looki-personal-memory`, synced into the plugin by workflow; releases publish to ClawHub as owner `looki` |
| The skill file | Byte-identical in both repos, sha256 prefix `76718777b5d9`, 11,691 characters. The older hosted skill URL (`web.looki.ai/agent/looki-memory/SKILL.md`) returns 404 |
| `@looki-ai/cli` | npm package, created 2026-09-24; v0.6.1 published 2026-11-10T02:01Z, during this program. Device-authorization login, config at `~/.looki/config.toml`, `--json` returns the raw server envelope |
| Hosted MCP | `https://open.looki.ai/mcp`, OAuth only (below) |

The skill describes six record types: memory overview, moments and
files, summaries, health reports, journals, and chat. looki-mcp
already covered moments and journals more deeply than the official
surface does (durable media capture to MinIO, backfill, video frame
extraction, VLM realtime description, none of which the official
stack offers). The other four types had no tool here at all. That
asymmetry set the work: the gap was exactly four record types, and
the open question was which surface they were reachable on.

## The OAuth wall

The hosted MCP server was probed live, unauthenticated, on
2026-11-09. It answers `401` with a `WWW-Authenticate: Bearer`
header pointing at its protected-resource metadata. The metadata
chain is complete and standards-shaped: authorization server at
`https://open.looki.ai`, endpoints `/oauth/authorize`,
`/oauth/token`, `/oauth/register`, and `/oauth/revoke`, grant
types `authorization_code` and `refresh_token`, PKCE S256 only,
and a single scope, `read`.

What is not available anywhere is the tool list. Neither repo
publishes tool names or schemas, and the skill explicitly instructs
agents to discover tools through the MCP client rather than guess.
Enumerating the hosted server's tools therefore requires a person
to complete one interactive browser OAuth flow in a supported
client (Claude Code's `/mcp` flow, for example). That enumeration
is still open. It is recorded here as an open item rather than a
blocker, for a precise reason: everything the skill and the CLI
promise turned out to be reachable on the API-key surface, so the
enumeration can only add information about the hosted server's own
shape; it cannot unblock any estate capability. If it is ever run
and shows a tool with no v1 counterpart, that is a new parity item
on its own evidence.

## The CLI command table is the probe generator

The morning probe of 2026-11-09 (the RP-115 discovery pass) had
called the API directly with a speculative path list, and it found
real things, including the `audio_summary` field. It also missed
four endpoints, and the miss is instructive: the speculative list
simply did not contain the exact names. `memory/overview`,
`summaries`, `health-reports`, and `chat/history` are not names a
guesser converges on quickly when the neighbouring conventions
suggest `/memory`, `/summary`, `/health`, and `/chat`, all of
which return 404.

The candidate generator that worked was the official CLI's command
table, read out of the skill: `looki memory overview`,
`looki summary list --type daily|weekly|chat`,
`looki health list`, `looki chat history --limit/--since`. Every
command in that table maps to a v1 path, and the four unknown
commands mapped to the four unknown endpoints. The probe harness
now records this as a standing rule, written into its header by
OB-69900: future probe candidates come from the official CLI
command table first, and speculative names second. A discovery
process that depends on guessing path names will keep missing
exactly the endpoints the vendor bothered to name differently.

## Four endpoints, verified live

Each endpoint below was verified on the API-key v1 surface on the
evening of 2026-11-09, with the key resolved on Furnace and never
printed. Record content was not copied into any working document;
what is recorded is field names, shapes, and the behavioural
contracts, which is all a client needs and all a parity record
should carry.

### Memory overview

`GET /memory/overview` returns one consolidated personal-context
record: `data {summaries, updated_at}`, where `summaries` carries
seven sections: `identity`, `lifestyle`, `traits`, `interests`,
`relationships`, `current_experiences`, and `looki_preferences`.
It is a single mutable vendor-generated snapshot, not a feed. That
shape drove two different treatments downstream: a simple wrapping
tool here, and an append-only snapshot table with hash dedup in
Nexus, because a mutable record with no history API only has a
history if the client keeps one.

### Summaries

`GET /summaries` takes `start_date` and `end_date` and a required
`type`. The verified type set is `daily`, `weekly`, `chat`, and
`moment`, lowercase only; `moment` was not in the skill's command
table and surfaced through the 422 enum error, a small reminder
that error bodies are documentation too. Items are
`{on_date, summary}`. Summaries are a distinct record from
journals: the journal family's recap artifacts are creative
outputs, while these are the vendor's per-day, per-week,
per-conversation, and per-moment digests, and conflating them
would have corrupted both tool families.

The range contract is the sharp edge. Spans over 7 days are
rejected with HTTP 400, code 100. A client that wants a month of
summaries must page adjacent 7-day windows and merge, which is
what `get_summaries` does and what the later Nexus sync inherited.

### Health reports

`GET /health-reports` takes `start_date` and `end_date` and
returns items `{date, tz, report_data}`, where `report_data`
carries `summary`, `calorie`, `daily_metrics`, `dietary_review`,
`events`, and `time_range`. The range contract here is the
opposite failure mode from summaries and the more dangerous one: a
wide range returns success, code 0, while silently truncating to
the first 30 days of the range. Nothing in the response says data
is missing. `get_health_reports` therefore pages adjacent 30-day
windows and merges, and the contract is written into the tool's
documentation and the probe's assertions, because any future
client written against this endpoint without that knowledge will
lose data while every check it runs reads green.

### Chat history

`GET /chat/history` returns cursor pages:
`{items, has_more, next_cursor}`, items `{role, text, created_at}`,
with `limit` and `since` parameters. The conversations are with
Looki's in-app assistant. Two shape facts shaped everything built
on top of it. First, there is no message id, anywhere in the item;
any store that needs idempotence has to derive a key, and the
Nexus ingest later derived a content hash over
`(role, created_at, text)` and proved against the full history
that it collides zero times. Second, `since` is loosely applied
upstream (a `since` of 2026-11-07 returned the full history during
the Nexus verification), so the tool here passes the cursor
through honestly and fabricates nothing: the caller pages, the
server says whether more exists, and no client-side shortcut
pretends otherwise.

### The traps, collected

| Candidate | Result | Classification |
|---|---|---|
| `date=` or `from_date`/`to_date` on summaries or health | 400, code 100, "Date parameter is required" | Misleading error; the required names are exactly `start_date`/`end_date` |
| `/summaries` without `type` | 422, missing `query.type` | Type is required, not defaulted |
| `/moments/dates`, `/journals/dates` | 422, path-parameter capture (`moment_id` / `journal_id`) | Not routes; the CLI's dates commands sit on other endpoints |
| `/summary`, `/health`, `/chat`, `/memory`, `/overview` and siblings | 404 | Singular and short variants do not exist |
| Hosted MCP, unauthenticated `initialize` | Timed out rather than a clean error | Noted; the 401 on GET is the documented door |

## The build: six tools, 24 to 30

The pack ran as OB-69894 through OB-69900 (OB-69901, the Nexus
ingest and census assessment, closed alongside and is recorded in
the nexus narrative). Each item was its own worktree, pull
request, and squash merge on 2026-11-09, and the set deployed
together at the final merge. An honest arithmetic note: the
original brief for the pack said "24 to 31 tools". Six tools were
added, and 24 plus 6 is 30. The close record corrects the brief
rather than repeating it.

| OB | PR | Merge | Tool |
|---|---|---|---|
| OB-69894 | #26 | `9cf1945` | `get_memory_overview` over `GET /memory/overview` |
| OB-69895 | #27 | `6cb6422` | `get_summaries` over `GET /summaries`, 7-day window paging |
| OB-69896 | #28 | `3a8a99f` | `get_health_reports` over `GET /health-reports`, 30-day window paging |
| OB-69897 | #29 | `519ba14` | `get_chat_history` over `GET /chat/history`, cursor passthrough |
| OB-69898 | #30 | `07cc30f` | Composites `get_day_context` and `get_personal_context` |
| OB-69899 | #31 | `5a8e223` | Contract docs: `models.py` re-stamp, `official_parity_api_findings.md` |
| OB-69900 | #32 | `1e0d4dc` | Probe re-baseline to the verified contract |

The composites deserve their sentence. `get_day_context` assembles
one date as labeled sections (moments at index level, the daily
summary, the health report, journals in summary mode), and
`get_personal_context` returns the memory overview with the most
recent daily and weekly summaries. A failing ingredient surfaces
as that section's `error` rather than failing the call, and every
section's content is returned in full, under the server's standing
rule that Looki content is never truncated.

Verification was three-layered. The offline suite (22 scripts)
ran green against the merged code. The re-baselined contract
probe, 29 requests, exits 0 against the live API, including the
negative assertions for the false routes and the parameter traps.
And the deployed service was checked from outside itself: the
tool list reads 30, and a live weekly-summaries call returned
records through the new paging path. The service runs the merged
build at `1e0d4dc`; this narrative ships docs-only on top of it
and restarts nothing.

## Options considered and rejected

Three alternatives were on the table and lost, for reasons worth
keeping next to the decision.

- **Migrate to the hosted OAuth MCP.** Rejected. It would trade a
  working server-side credential for per-client interactive auth,
  which does not fit a headless server; it would lose the
  capabilities the official stack does not have (MinIO media
  capture, backfill, frame extraction, VLM describe); and its tool
  list is unpublished and unenumerated, so the migration target
  cannot even be inventoried before committing to it.
- **Adopt `@looki-ai/cli` as a runtime dependency.** Rejected.
  Its login is an interactive device flow with per-machine config
  at `~/.looki/config.toml`, which is a workstation tool's shape,
  not a service dependency's. The CLI earned its place in this
  program as a discovery instrument, the candidate generator for
  probes, and that is the role it keeps.
- **Wait for the hosted enumeration before building.** Rejected.
  Every promised record type was verified reachable on the
  API-key surface the same evening; waiting would have held four
  working endpoints hostage to a browser flow that can only add
  information, never unblock capability.

## The watch, and its known gap

The repos are enrolled in the estate's existing nightly
upstream-digest rather than in any new machinery: the `looki-ai`
organization is on the watched-accounts roster (a new repo under
the org surfaces against the baseline of two), and both
`looki-ai/looki-plugin` and `looki-ai/looki-skills` are on the
discovery watch for HEAD movement and releases. The digest reads
both rosters fresh each run, so enrollment was a roster edit, not
a new job.

The gap is stated plainly so a future reader does not rediscover
it as a surprise: `@looki-ai/cli` is npm-only with no public repo,
so its version moves do not surface through a GitHub watch. The
proxy signal is the skill-sync commits in the watched repos,
which is how CLI-adjacent changes have arrived so far (v0.6.1
itself published during this program and was caught by direct
registry check, not by the watch).

## What this leaves behind

The server is at parity with the official stack on every record
type the vendor documents, and ahead of it on capture, backfill,
and media. The four endpoints are no longer a looki-mcp-only
surface: Nexus ingests all four and carries them through its
medallion layers, which is the nexus narrative's story. What
remains genuinely open is small and specific. The hosted MCP's
tool list is unenumerated, awaiting one interactive OAuth flow
whenever that is worth an operator's minute. And the next parity
question is already scheduled by the watch rather than by memory:
when the org ships a third repo, or the skill's record list grows
a seventh type, the digest will say so, and the probe rule
(CLI table first, speculation second) is written down where the
next pass will find it.

See `CHANGES.md` for the chronological diff summary.

> Executed by Muse ship worker (model: Muse Wonder), 2026-11-10.
