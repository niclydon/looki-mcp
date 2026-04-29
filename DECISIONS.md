# Design Decisions

This file documents the key architectural and technology decisions made for `looki-mcp`,
and the reasoning behind each. New contributors should read this before proposing changes
to the core architecture.

---

## Language: Python (not TypeScript)

**Decision:** Python 3.11+

**Why not TypeScript:**
This server is a public open-source tool for the Looki community, not a private homelab
service. For a public repo, the right language is the one that:

- Minimizes setup friction for contributors and end users
- Requires no build step (TypeScript requires `npm run build` before `npm start`)
- Has the widest reach among potential contributors
- Matches community expectations for MCP server projects

Python wins on all counts for a public-facing tool. The maintainer's other MCP servers
are TypeScript, but consistency with private-stack tooling does not outweigh
accessibility for a public repo.

---

## MCP Framework: fastmcp (not the raw `mcp` SDK)

**Decision:** `fastmcp` ≥ 2.0

**Why not the raw `mcp` SDK directly:**
The official Python `mcp` SDK requires manual schema definition and handler wiring.
`fastmcp` provides a decorator-based API (`@mcp.tool`) where tool schemas, validation,
and documentation are generated automatically from type hints and docstrings.

`fastmcp` has become the de facto standard for public/community Python MCP servers.
Its decorator pattern keeps tool code readable enough that contributors unfamiliar
with MCP internals can understand and modify tools immediately.

`fastmcp` itself is built on top of the official `mcp` SDK, so we get the
authoritative protocol implementation underneath.

---

## HTTP Transport Only (no stdio)

**Decision:** HTTP transport via `mcp.run(transport="http")`

**Why:**
This server is designed for remote deployment and connection via claude.ai, Claude
Desktop (remote HTTP mode), or other MCP-compatible clients that connect over a URL.

Stdio transport is for locally-spawned subprocesses (such as IDE integrations launched
by Claude Desktop). Adding stdio support would add complexity with no benefit for
this use case — users running `python main.py` on their server are connecting to it
remotely.

---

## Credentials: Environment Variables

**Decision:** `LOOKI_BASE_URL` and `LOOKI_API_KEY` via `.env` file

**Why:**
Environment variables are the standard for self-hosted server credentials. They are:

- Gitignored automatically (`.env` excluded via `.gitignore`)
- Docker-compatible (`env_file` in `docker-compose.yml`)
- Familiar to any developer who has deployed a web service

The Looki ClaWHub skill recommends `~/.config/looki/credentials.json` for AI agent
use, but that pattern is for conversational AI tools where an LLM handles the
credentials in real time. For a server process, environment variables are the
correct and secure approach — the API key never touches the model's context.

---

## Startup Credential Validation

**Decision:** Validate and verify credentials before the server accepts connections

**Why:**
A server that starts successfully but fails on the first tool call is harder to debug
than a server that fails fast with a clear error message. On startup, `looki-mcp`:

1. Checks that both required env vars are present
2. Validates the API key format (`lk-` prefix)
3. Validates the port range (1–65535)
4. Calls the Looki verification endpoint to confirm the base URL is reachable and accepted

If any check fails, the server exits with a clear, actionable error message including
suggested fixes. This makes setup self-diagnosing.

---

## MCP Endpoint Path: `/mcp`

**Decision:** Default fastmcp HTTP path (`/mcp`)

**Why:**
fastmcp's HTTP transport serves the MCP endpoint at `/mcp` by default. Custom routes
(health, logo) are added at `/health` and `/logo.ico`. This separation makes the
server's purpose clear: `/mcp` is for MCP protocol traffic, other paths are for
operations (monitoring) and presentation (logo).

---

## Logo / Icon

**Decision:** Serve `assets/looki-logo.ico` at `/logo.ico` via `@mcp.custom_route`

**Why:**
The MCP specification supports server icons in client UI. By serving the Looki logo
at a predictable path and exposing `LOOKI_MCP_BASE_URL` as a configuration knob,
users can enable the Looki branding in claude.ai, Claude Desktop, and other clients
without modifying server code.

The logo is included in the repository (rather than fetched at runtime) to ensure
the server works in offline / air-gapped environments and is not dependent on
`web.looki.ai` remaining reachable.

---

## Timezone Handling: Optional Server-Level Setting

**Decision:** Optional `LOOKI_USER_TIMEZONE` env var (IANA name). When unset,
the two date-computing convenience tools default to UTC. Responses always
include both `*_local` and `*_utc` dates plus the resolved timezone name.

**Why:**
The typical deployment is one user running their own MCP server. They know
their timezone at deploy time and can set it once. A public MCP server has
no reliable way to detect the consumer's timezone — the request comes through
firewalls, proxies, and cloud deploys that all strip or rewrite timezone
hints, and HTTP itself has no useful equivalent of a "user timezone" header.

A server-level env var is:
- Explicit (no magic detection)
- Validated on startup via `zoneinfo` (bad values fail fast)
- Easy to omit for shared/multi-user deployments where UTC is the only safe shared default
- Discoverable (documented in README and `.env.example`)

We deliberately do **not** try to handle Looki's per-moment `tz` field (which
uses UTC offsets like `-04:00`) as the server's timezone. That field is
attached to individual captured moments and travels with them; it isn't a
property of the user. We pass it through unchanged so the AI assistant can
reason about each moment's local time independently.

The two convenience tools (`get_recent_activity`, `get_todays_moments`) are
the only ones that *compute* dates; everything else takes user-supplied
`YYYY-MM-DD` arguments verbatim, so timezone never enters the picture.

---

## TLS / HTTPS Support

**Decision:** Optional direct TLS via `LOOKI_TLS_CERT_PATH` and `LOOKI_TLS_KEY_PATH`
env vars. When unset, the server binds plain HTTP and assumes a TLS-terminating
reverse proxy is in front.

**Why both modes:**
- **Reverse proxy** (Cloudflare Tunnel, Caddy, nginx, Tailscale Funnel) is the
  most common deployment pattern for personal MCP servers — easier cert
  management (auto-renew, multi-host), and the server stays simple.
- **Direct TLS** is needed for users who run on a single VPS without a proxy,
  or in air-gapped environments where Let's Encrypt isn't reachable but they
  have an internal CA.

**Why not enforce HTTPS-only by default:**
A "HTTPS-only" default would force every user to handle certs, which doesn't
match how most people deploy MCP servers (proxy-fronted). Instead the README
positions HTTPS as the recommended public-exposure mode and the startup banner
makes it explicit which mode is active so misconfiguration is loud.

**Why both vars (cert AND key):**
Both must be set together or neither — half-set TLS config exits on startup
with a clear error. Files are validated to exist before the server attempts
to bind, so cert/key path typos fail fast rather than after a partial startup.

---

## Per-Request httpx Client

**Decision:** New `httpx.AsyncClient` per tool invocation via `async with get_client() as client:`

**Why:**
A long-lived client would have lower per-request overhead, but adds lifecycle
complexity (especially around fastmcp's request handling). For an MCP server making
occasional API calls (not high-throughput), the connection-pool overhead per request
is negligible. Per-request clients simplify the code and avoid resource leaks if a
tool errors mid-flight.

---

## Error Handling: String responses, not exceptions

**Decision:** Tools return `f"Error: {message}"` strings on failure rather than raising

**Why:**
fastmcp tools that raise exceptions surface those as MCP protocol errors, which most
clients render less helpfully than tool text content. Returning a structured error
string lets the AI assistant read the actual problem (rate limit, network, bad ID)
and respond intelligently — e.g., suggesting the user wait a minute, or asking for
a different moment ID.

API keys are never included in error strings, even on auth failures.
