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
