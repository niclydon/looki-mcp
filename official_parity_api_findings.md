# Looki official-parity API findings

Verified live 2026-11-09 (evening ET) from Furnace with the account API
key resolved in place; zero rate-limit responses. This document records
the second Looki contract layer discovered by the RP-116 parity pass:
four endpoints on the API-key surface that the pre-2026-11-09 contract
did not carry, plus the official hosted-MCP / CLI stack as upstream
context. Field shapes are also documented per-model in
`looki_mcp/models.py`.

## New endpoints on the API-key surface (all live, envelope code 0)

### GET /memory/overview
- data: `{summaries, updated_at}`
- summaries keys: identity, lifestyle, traits, interests, relationships,
  current_experiences, looki_preferences
- A consolidated personal-context summary, not an event timeline.
- Wrapped by tool `get_memory_overview` (OB-69894).

### GET /summaries
- Required params: exactly `start_date`, `end_date`, `type`.
- type enum: daily | weekly | chat | moment (lowercase only; an uppercase
  value returns 422 and the error reveals the full enum). Omitting `type`
  returns 422 (missing query.type).
- data: `{type, items[{on_date, summary}]}`
- Param trap: passing `date=` or `from_date`/`to_date` returns a
  misleading HTTP 400, envelope code 100, "Date parameter is required".
- Range contract (verified live 2026-11-09): spans longer than 7 days
  are rejected for the daily-type records (8-day daily span -> HTTP 400
  code 100; 7 days OK). `get_summaries` pages longer ranges as adjacent
  non-overlapping 7-day windows and merges (OB-69895).

### GET /health-reports
- Required params: exactly `start_date`, `end_date` (same 400 code 100
  trap as /summaries).
- data: `{items[{date, tz, report_data}]}`
- report_data keys: summary, calorie, daily_metrics, dietary_review,
  events, time_range. Values are Looki's own observations/estimates.
- Range contract (verified live 2026-11-09): wide ranges are SILENTLY
  truncated to the first 30 days of the range (a 2026-09-01..2026-11-08
  request returned only 2026-09-01..2026-09-30, code 0, no error).
  `get_health_reports` pages ranges as adjacent non-overlapping 30-day
  windows and merges (OB-69896).
- The route is the plural /health-reports; /health and /health/reports
  are 404.

### GET /chat/history
- Params: `limit`, `since` (ISO 8601 with offset), `cursor`.
- data: `{items[{role, text, created_at}], has_more, next_cursor}`;
  cursor round-trip verified live (page 2 returns code 0).
- Wrapped by tool `get_chat_history` (OB-69897), default limit 50
  (matching the official CLI examples), cursor passed through opaquely.
- /chat, /chats, /chat/messages, /chat/summaries are all 404. Chat
  summaries are the /summaries record with type=chat.

## False routes
- /moments/dates and /journals/dates are NOT endpoints: they return
  HTTP 422 with the validation loc pointing at the detail route's path
  param (["path","moment_id"] / ["path","journal_id"]) — path-param
  capture, the same trap class as /moments/{non-UUID}. The official
  CLI's `moment dates` / `journal dates` commands sit on top of other
  endpoints.
- Singular variants all 404: /memory, /overview, /summary,
  /life-summaries, /health, /health/reports, /chat, /chat/summaries,
  /chats, /chat/messages.

## Official stack inventory (upstream context, NOT our dependencies)

- Repos: looki-ai/looki-plugin (v1.0.3, 2026-11-04) and
  looki-ai/looki-skills — the only two public repos in the looki-ai org.
  Both carry the single skill `looki-personal-memory` (SKILL.md sha256
  prefix 76718777b5d9, byte-identical in both; synced into the plugin by
  workflow; skills releases publish to ClawHub under owner `looki`).
- Hosted MCP: https://open.looki.ai/mcp — OAuth only. Unauthenticated
  GET returns 401 with WWW-Authenticate Bearer and resource_metadata at
  https://open.looki.ai/.well-known/oauth-protected-resource/mcp.
  Authorization server https://open.looki.ai: /oauth/authorize,
  /oauth/token, /oauth/register (dynamic client registration),
  /oauth/revoke; grant types authorization_code + refresh_token; PKCE
  S256 only; scope `read` only. The hosted MCP's tool names/schemas are
  published nowhere; the skill instructs agents to discover them via the
  client. Enumerating them requires an interactive browser OAuth flow.
- CLI: @looki-ai/cli on npm (created 2026-09-24; v0.6.1 published
  2026-11-09). Bin `looki`; device-authorization login (`looki login`,
  `looki auth status`); config at $LOOKI_HOME/config.toml (default
  ~/.looki/config.toml); `--json` returns the original server envelope.
  Command table: `looki memory overview`, `looki moment
  list/search/dates/view/files`, `looki journal list/dates/view`,
  `looki summary list --type daily|weekly|chat`, `looki health list`,
  `looki chat history --limit/--since`.
- The old upstream skill URL
  https://web.looki.ai/agent/looki-memory/SKILL.md returns 404; the
  canonical skill is now `looki-personal-memory` in looki-ai/looki-skills.

## Probe candidate-generation rule

The 2026-11-09 morning probe missed all four endpoints because its
speculative path list lacked the exact names. Future probe candidates
come FIRST from the official CLI command table + the skill's record
types, and only second from speculative names. scripts/api_contract_probe.py
carries this rule in its header (OB-69900).

## Decisions recorded by RP-116
- No migration to the hosted OAuth MCP: it would lose durable media
  capture, backfill, frame extraction, VLM realtime description, and the
  Nexus ingest path, and per-client interactive auth does not fit a
  server.
- @looki-ai/cli is not a runtime dependency (interactive device login,
  per-machine config).
- No /moments/dates- or /journals/dates-style tools (false routes).
