# The Vendor Published the Docs, and One Number in Them Had Moved

On the evening of 2026-11-11 the operator dropped three links into a
side chat with no other instruction than "Looki updates":
`platform.looki.ai/en/agents`, `platform.looki.ai/en/cli`, and
`platform.looki.ai/en/api-reference`. Looki had never had a public
developer platform site before. The estate's knowledge of the Looki
API had been assembled the hard way across July, October, and
November 2026: an agent skill file fetched from the vendor's web app,
roughly 130 speculative live probes against
`https://open.looki.ai/api/v1`, two GitHub repos discovered the week
before, and an npm CLI whose command table turned out to be the
reliable map of the record types. The RP-57 narrative in this repo
records the July state plainly: there was no OpenAPI JSON on
`open.looki.ai` (`/openapi.json`, `/docs`, and `/swagger` all 404),
and the canonical public contract was a skill file.

A vendor publishing real docs is good news and a verification
problem at the same time. The good news is obvious. The problem is
that a published reference is a claim about the API, and this estate
had been burned in both directions within the previous month:
endpoints the skill never mentioned that were live all along
(`/memory/overview`, `/summaries`, `/health-reports`, `/chat/history`,
found 2026-11-09), and endpoints the skill implied that upstream had
retired (`/for_you/items` in October, `/journals/by_date` in
November). So the three pages were read the way this repo reads
everything from the vendor now: as a candidate list to be checked
against the live API and against the server's own verified contract,
not as ground truth. The check produced no new surface, one vendor
documentation omission, and one real upstream change that had
already invalidated four statements in this repo.

## Where the server stood

The timing mattered. The night before, track RP-116 had closed and
shipped: the six parity tools (PRs #26–#32, deployed at `1e0d4dc`),
the narrative at `docs/narrative/2026-11-10-official-parity-rp116.md`
(PR #33, `fa9d54b`), and the downstream Nexus ingest of the four new
record types. The running service carried 30 tools and had just been
verified end to end. The estate's upstream watch already covered the
`looki-ai` GitHub org and both of its repos through the nightly
digest; the npm-only CLI was the watch's known gap, with skill-sync
commits in the watched repos as its proxy signal.

Into that settled state, the Platform site was the vendor's first
consolidated public statement of the same surface: an Agents page
(how to connect an agent), a CLI Reference (the terminal client),
and an API Reference carrying an OpenAPI 3.1.0 label. Nothing in the
estate's posture depended on the site existing, which made it a clean
test of the estate's own contract: if the repo's verified state and
the vendor's published state agreed, the publication was a
non-event; where they disagreed, the live API would arbitrate.

## The three pages, inventoried

### Agents

Three access methods, presented as alternatives of which an agent
needs exactly one:

- Plugins (recommended): `npx plugins add looki-ai/looki-plugin`,
  no separate skills install or MCP configuration.
- Skills: `npx skills add looki-ai/looki-skills`, then ask the agent
  to install the CLI and produce a login link.
- MCP: point a remote-MCP-capable agent at
  `https://open.looki.ai/mcp` and complete authorization manually.

The troubleshooting table names the four expected failure shapes:
CLI not on PATH, agent not discovering an installed skill or plugin,
CLI authentication failure (`looki auth status`, then
`looki login`), and MCP connection failure. All of this matched the
RP-116 inventory of the official stack file by file. The estate's
standing rejection of the hosted OAuth MCP was unaffected by seeing
it in vendor marketing form: migrating would still lose durable
MinIO media capture, journal backfill, video frame extraction, and
the Nexus ingest path, and per-client interactive OAuth still does
not fit a server.

### CLI Reference

The CLI page lists 21 commands: `login`, `logout`, `auth status`,
`auth refresh`, `memory overview`, the five moment commands (list,
search, dates, view, files), the three journal commands (list,
dates, view), `summary list`, `health list`, `chat history`, and
five config commands (list, set, get, unset, path), with
configuration in `~/.looki/config.toml` and a `LOOKI_HOME` override.
The constraints the page states are the constraints the server
already encodes, which is worth recording because two of them were
originally discovered as traps:

| CLI statement | Estate's prior knowledge |
|---|---|
| Summary daily/chat ranges up to 7 days; weekly up to 31, filtered by week end date | `/summaries` rejects spans over 7 days with HTTP 400, code 100; `get_summaries` pages adjacent 7-day windows (found live 2026-11-09) |
| Health ranges up to 30 inclusive days | `/health-reports` silently truncates wider ranges to the first 30 days with code 0; `get_health_reports` pages 30-day windows (found live 2026-11-09) |
| Chat `--since` requires an explicit timezone when supplied | Matches the chat-history contract recorded in `models.py` |
| `moment search` limit 1–100, default 10; query unchanged across cursor pages | New in print, consistent with observed behavior; the API Reference adds a 1–100 character query bound |

### API Reference

Fourteen endpoints under the `X-API-Key` header, all already in
this server's upstream path set:

| Group | Endpoints |
|---|---|
| Account | `GET /me` |
| Memory | `GET /memory/overview` |
| Moments | `GET /moments`, `/moments/search`, `/moments/calendar`, `/moments/{id}`, `/moments/{id}/files` |
| Journals | `GET /journals`, `/journals/calendar`, `/journals/{id}` |
| Summaries | `GET /summaries` |
| Health | `GET /health-reports` |
| Chat | `GET /chat/history` |
| Realtime | `GET /realtime/latest-event` |

The page also states the platform's operating limits in one place
for the first time: 60 requests per minute per API key, HTTP 429 on
excess, retry after 60 seconds; API keys are issued in the vendor's
console and must only ever be sent to `https://open.looki.ai`. The
rate limit was not news (the older skill file carried the same 60
per minute, and the contract probe has always paced itself well
under it), but its publication moves it from folklore to contract.

No endpoint, record type, or parameter in the three pages was new.
That sentence is the parity verdict, and it is the second time in
three days the estate's probed contract and the vendor's stated
contract have agreed on the inventory. They disagreed on two
details, and the details are the rest of this document.

## Discrepancy one: the missing summary type

The API Reference describes `/summaries` as returning "daily
activity, weekly, or chat summaries", and its `type` parameter as
"exactly one summary type: daily, weekly, or chat". The CLI page
says the same. But on 2026-11-09 the live API's own validation error
had revealed a four-member enum, and `get_summaries` was built and
shipped supporting all four, `moment` included. Either the vendor
had removed the type in the two days since, or the published docs
were incomplete. The operator chose the live re-probe.

Method, as with every probe in this repo's history: a script run on
Furnace with the account key resolved in-process from the service
environment and never printed, paced single requests, printing only
status codes, envelope codes, counts, dates, and field names — never
record content. The window was 2026-11-05 through 2026-11-11.

| `type` | HTTP | Code | Items | Dates |
|---|---|---|---|---|
| daily | 200 | 0 | 6 | 2026-11-05 … 2026-11-10 |
| weekly | 200 | 0 | 1 | 2026-11-08 |
| chat | 200 | 0 | 1 | 2026-11-08 |
| moment | 200 | 0 | 6 | 2026-11-05 … 2026-11-10 |

A second window (2026-10-12 through 2026-10-18) returned 7 moment
summaries, one per day, so the November result was not a residue of
soon-to-expire records. The invalid-type control settled it: a
request with a deliberately bogus type returned HTTP 422 with the
API's own enum in the message, verbatim: "Input should be 'daily',
'weekly', 'chat' or 'moment'". The type is live, the enum still
names it, and the published Platform docs simply omit it.
`get_summaries` needed no change. The lesson is the mirror image of
the 2026-11-09 morning probe: that probe missed four live endpoints
because its candidate list came from speculation; this one would
have deleted a live type if its candidate list had come from the
vendor's newest documentation. Docs propose, the API disposes, in
both directions.

## Discrepancy two: the ten-minute URL

The API Reference states, under "File URLs": pre-signed media URLs
expire after 10 minutes; request fresh data when a URL expires.
This repo's verified state said otherwise. `models.py` recorded, in
the FileModel docstring, a host change observed 2026-11-09
(`user-file.looki.ai` replacing `devo-user-file.looki.ai`) and the
observation that "the observed JWT expiry remains about one hour
for this presigned host". The same ~1 hour figure stood in the
JournalMediaFile field comment, in the `get_moment_files` tool
description ("valid 1 hour"), and in `journals_api_findings.md`.
Older records said 10 minutes on the old host: the June 2026
narrative in this repo decodes a journal `temporary_url` JWT to
prove the ten-minute life that made MinIO capture necessary, and
the RP-57 narrative (2026-07-18) records "JWT expiry still ~10
minutes" on `devo-user-file.looki.ai`. So the number had already
moved once, 10 minutes to ~1 hour, somewhere around the host change,
and the Platform docs were now claiming it had moved back — or
claiming a number that had never applied to the moment-file surface
at all. The blanket wording ("media URLs", no surface distinction)
made a per-surface probe necessary: if journal media lived 10
minutes and moment files lived an hour, the correct fix would be a
split statement, not a global replacement.

The probe fetched fresh data in each surface and decoded the
`x-looki-token` JWT carried in the query string of each returned
URL, printing only the host, the first path segment, the claim
names, and the arithmetic — never a full URL or a token. Surfaces
sampled, all within the same minute on 2026-11-11 at 21:34 ET
(2026-11-12T02:34Z): moment covers from the moments list for
2026-11-11 (12 moments that day; calendar confirmed moments on
every day from 2026-10-28 through 2026-11-11), five files from
`GET /moments/{id}/files` for the day's first moment, and the media
of a journal entry drawn from a 61-entry, 7-day feed sample.

| Surface | Host | JWT ttl (exp − iat) | Remaining at fetch |
|---|---|---|---|
| Moment cover | `user-file.looki.ai` | 600s | 599s |
| Moment files | `user-file.looki.ai` | 600s | 599s |
| Journal media | `user-file.looki.ai` | 600s | 599s |

Uniform, and not close: the published 10 minutes is the current
truth on every surface, and the ~1 hour recorded two days earlier
is superseded. The exact moment of the change is unknowable from
outside (the estate's samples bracket it between the 2026-11-09
observation and the 2026-11-11 probe), and no attempt was made to
pin it further; the JWT's own `exp` claim is the server-enforced
expiry, so an empirical wait-and-refetch burn test would have added
eleven minutes and no information. What matters operationally is
the direction of the error: every consumer this server hands a
moment file URL to was planning around an hour it does not have.
The capture paths were already safe (journal media capture was
designed against the ten-minute life in June and downloads
immediately on read), but an agent that listed moment files,
reasoned for twenty minutes, and then fetched would have met dead
links and, until this fix, a tool description assuring it otherwise.

## The fix

The operator was offered two dispositions — fix the stale claims
directly, or file them into the operator backlog — and chose the
direct fix. PR #34 (`nova/media-url-expiry-10min`, worktree build,
squash-merged as `b00eb05`) touched four files, documentation and
comments only:

- `looki_mcp/tools/moments.py` — the `get_moment_files` description
  now reads "valid ~10 minutes".
- `looki_mcp/models.py` — the FileModel docstring records the
  2026-11-11 re-verification (exp−iat = 600s across moment covers,
  moment files, and journal media) as superseding the 2026-11-09
  ~1 hour observation, and the JournalMediaFile comment carries the
  same dated figure.
- `journals_api_findings.md` — the media section states the 600s
  expiry with its verification date.
- `CHANGES.md` — the chronological entry for the correction,
  including the summary-type confirmation from the same probe.

Historical narratives and design specs were deliberately left as
written: they are dated records, several of them already state
~10 minutes from their own observation dates, and rewriting them
would have destroyed exactly the oscillation evidence (10 minutes
in June and July, ~1 hour in early November, 10 minutes again by
2026-11-11) that a future reader needs. The offline suite passed
22 of 22 scripts under the service virtualenv (the live suite,
`test_all_tools.py`, skipped as usual), the deploy ran through
`scripts/deploy.sh` to `/services/looki-mcp` at `b00eb05` with the
script's health check ok, and the deployed server was verified from
the operator's seat: 30 tools listed, and `get_moment_files` serving
the corrected description. The worktree and both branches were
removed; the canonical checkout stands clean on `main` at
`b00eb05`, equal to `origin/main` and to the deployed sha.

## Options considered and not taken

Re-baselining `api_contract_probe.py` against the published OpenAPI
reference was offered alongside the fix and not chosen; the probe
already covers all 14 endpoints after OB-69900, and the two
discrepancies this arc found were both settled by targeted live
calls. It remains the natural next step if the vendor's published
spec and the live API diverge again, and one assertion is worth
adding whenever that re-baseline happens: decode one fresh media
JWT and assert its ttl, because expiry has now proven to be a
moving number that no document, including this one, can freeze.

Migrating to the vendor's hosted MCP or adopting the official CLI
as a runtime dependency were not reconsidered; RP-116 rejected both
with reasons that the Platform site does nothing to change.

## What this leaves behind

The durable lesson is about the half-life of observed constants.
This repo now holds three dated, honestly observed values for one
number — ~10 minutes, ~1 hour, 600 seconds — and all three were
true when written. Any undated expiry claim in a tool description
is therefore a small lie on a timer; the fix's convention (state
the figure with its verification date and name the observation it
supersedes) is the pattern the next drift should follow. Upstream,
the Platform site's existence changes the discovery order for the
next parity pass without changing its arbiter: the published
reference joins the CLI command table as a candidate generator of
record, ahead of speculation, and behind the live API — a ranking
this arc earned from both directions in a single evening, once when
the docs omitted a live type and once when they reported a change
the estate's own fresher-looking notes had missed.

Still open, unchanged from the RP-116 close: the hosted MCP's tool
list remains unenumerated pending one interactive OAuth flow, and
the npm CLI's version moves remain invisible to the GitHub-based
upstream watch. Neither blocked anything here.

See `CHANGES.md` for the chronological diff summary.

> Executed by Nova (model: Muse Wonder), 2026-11-11.
