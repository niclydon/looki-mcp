# looki-mcp

An MCP (Model Context Protocol) server for the [Looki](https://web.looki.ai) wearable
camera — giving Claude, ChatGPT, and other AI assistants access to your personal
memories, moments, photos, and AI-generated highlights.

## What It Does

Looki L1 is a wearable camera that passively captures your daily life. This MCP server
exposes your Looki data through 12 tools that AI assistants can use to answer questions like:

- "What did I do last Thursday?"
- "Find the moment where I was at the coffee shop"
- "Show me my recent highlights"
- "What have I been up to this week?"
- "What am I doing right now?" *(requires Proactive Mode)*

## Prerequisites

- **Python** 3.11 or later (or Docker)
- A **Looki account** with an L1 device
- Your Looki **base URL** and **API key** (see below)

## Getting Your Credentials

1. Go to [web.looki.ai/api-keys](https://web.looki.ai/api-keys)
2. Generate a new API key (or use an existing one)
3. Copy your **Base URL** and **API Key** (starts with `lk-`)

## Installation

```bash
git clone https://github.com/yourusername/looki-mcp.git
cd looki-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The Looki logo (`assets/looki-logo.ico`) ships with the repo — nothing to fetch.

## Configuration

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
LOOKI_BASE_URL=https://your-looki-base-url
LOOKI_API_KEY=lk-your-api-key-here
LOOKI_PORT=3456
LOOKI_MCP_BASE_URL=https://looki-mcp.yourdomain.com   # optional, enables icon display
ORIGIN_SHARED_SECRET=                                  # optional, request-level auth
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `LOOKI_BASE_URL` | yes | Your Looki API base URL — generate at [web.looki.ai/api-keys](https://web.looki.ai/api-keys) |
| `LOOKI_API_KEY` | yes | API key starting with `lk-` |
| `LOOKI_PORT` | no | HTTP port for the server (default: `3456`) |
| `LOOKI_MCP_BASE_URL` | no | Public URL of this server, used for icon display in MCP clients |
| `LOOKI_USER_TIMEZONE` | no | IANA timezone name (e.g. `America/New_York`) for "today"/"recent" date calculations. Defaults to UTC when unset. See [Timezone Handling](#timezone-handling) below. |
| `LOOKI_TLS_CERT_PATH` | no | Path to TLS certificate file (PEM). When set together with `LOOKI_TLS_KEY_PATH`, the server serves HTTPS directly. See [TLS / HTTPS](#tls--https) below. |
| `LOOKI_TLS_KEY_PATH` | no | Path to TLS private key file (PEM). Must be set together with `LOOKI_TLS_CERT_PATH`. |
| `ORIGIN_SHARED_SECRET` | no | Shared secret required in the `x-origin-secret` header on every request. Strongly recommended for any public deployment. See [Origin Secret](#origin-secret) below. |

### Origin Secret

`ORIGIN_SHARED_SECRET` is a simple but effective gate: every request to `/mcp`
must include an `x-origin-secret: <value>` header that matches the env-var
value, or the server returns `401 Unauthorized`.

**Why you want this for public deployments:**
Without the secret, the server URL itself is your only "auth" — anyone who
discovers it can call your tools, drain your 60 req/min Looki rate limit, and
read your captured memories. With it, even if someone finds the URL they
can't make tool calls without the matching secret.

**Generate a strong secret:**
```bash
openssl rand -hex 32
# 64 hex chars — copy this into .env as ORIGIN_SHARED_SECRET=...
```

**Configure your MCP client to send the header.** In Claude Desktop's
`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "looki": {
      "type": "http",
      "url": "https://looki-mcp.example.com/mcp",
      "headers": { "x-origin-secret": "your-64-char-hex-string" }
    }
  }
}
```

In claude.ai's Integrations UI, add the same header field when configuring
the MCP server.

**What's exempt:** `/health` (so monitoring still works) and `/logo.ico` (so
MCP clients can fetch the icon during pre-session metadata exchange).

**What it does NOT replace:**
- TLS — the secret is sent in cleartext over plain HTTP and can be sniffed.
  Only meaningful when paired with HTTPS (direct or via reverse proxy).
- Per-user auth — anyone with the secret can impersonate the legit client.

The startup banner reports `Origin-secret guard ENABLED` or `DISABLED` so
you can see which mode is active in your logs.

### TLS / HTTPS

MCP clients like claude.ai require the server URL to be HTTPS for any public deployment.
You have two ways to satisfy that:

#### Option 1 — Reverse proxy in front (recommended for most users)

Run the server as plain HTTP on a private network or localhost, and put a TLS-terminating
reverse proxy in front. The server doesn't need to know about TLS.

Common choices:
- **Cloudflare Tunnel** — zero-config public HTTPS, free tier covers personal use
- **Tailscale Funnel** — public HTTPS over Tailscale, no port forwarding needed
- **Caddy** — `caddy reverse-proxy --to localhost:3456 --from looki-mcp.example.com`
- **nginx** — standard `proxy_pass` config

Leave `LOOKI_TLS_CERT_PATH` and `LOOKI_TLS_KEY_PATH` unset for this mode.

#### Option 2 — Direct HTTPS (server binds TLS itself)

Set both env vars to PEM-format files:

```
LOOKI_TLS_CERT_PATH=/etc/letsencrypt/live/looki-mcp.example.com/fullchain.pem
LOOKI_TLS_KEY_PATH=/etc/letsencrypt/live/looki-mcp.example.com/privkey.pem
```

The server validates both files exist on startup; it exits with an error if either
is missing or only one of the pair is set. The startup banner reports `https://`
when TLS is active.

For a Let's Encrypt cert via certbot:

```bash
sudo certbot certonly --standalone -d looki-mcp.example.com
# Then point the env vars at /etc/letsencrypt/live/looki-mcp.example.com/{fullchain.pem,privkey.pem}
# Make sure the user running looki-mcp can read those paths.
```

For testing locally with a self-signed cert:

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 \
    -nodes -subj "/CN=localhost"
LOOKI_TLS_CERT_PATH=$(pwd)/cert.pem LOOKI_TLS_KEY_PATH=$(pwd)/key.pem python main.py
# MCP clients won't accept self-signed certs by default — this is for verification only.
```

### Timezone Handling

Most tools take explicit `YYYY-MM-DD` dates as arguments and pass them through to the
Looki API verbatim — those tools are timezone-agnostic.

The two convenience tools that compute dates themselves (`get_recent_activity`,
`get_todays_moments`) need to know what "today" means. Behavior:

- **`LOOKI_USER_TIMEZONE` set** (e.g. `America/New_York`): "today" is the current
  date in that timezone. The value is validated on startup against `zoneinfo` —
  invalid names cause the server to exit with a clear error.
- **`LOOKI_USER_TIMEZONE` unset**: "today" is the current UTC date.

Either way, every response from these tools includes **both** `*_local` and `*_utc`
date fields plus the configured `timezone` name, so the AI assistant or human consumer
can always see exactly which calendar boundary was used. Example response from
`get_todays_moments`:

```json
{
  "date_local": "2026-04-29",
  "date_utc":   "2026-04-30",
  "timezone":   "America/New_York",
  "moments":    [ ... ]
}
```

Why a server-level setting (not per-request)? The typical deployment is one user
running their own MCP server. The user knows their own timezone once at deploy
time. A public MCP server has no reliable way to detect the consumer's timezone
across firewalls/proxies/cloud deploys, so an explicit env var beats guessing.

If you're sharing one server across multiple users in different timezones, leave
`LOOKI_USER_TIMEZONE` unset — UTC is the only correct shared default — and have the
AI assistant convert in the conversation.

## Running

```bash
python main.py
```

Expected startup output:

```
looki-mcp: Verifying Looki base URL...
looki-mcp: Base URL verified OK.
[looki-mcp] Server running on http://0.0.0.0:3456/mcp (12 tools)
```

The server validates your credentials before accepting connections — if anything is
wrong (missing var, malformed API key, unreachable base URL), it exits with a clear
error message explaining what to fix.

## Connecting to Claude

### claude.ai

1. Go to **Settings → Integrations → Add MCP Server**
2. Enter your server URL: `http://your-server:3456/mcp`
3. The Looki logo will appear if `LOOKI_MCP_BASE_URL` is set

### Claude Desktop (remote HTTP)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "looki": {
      "type": "http",
      "url": "http://your-server:3456/mcp"
    }
  }
}
```

## Deployment (systemd)

If you're running on a Linux server and prefer systemd to Docker, a unit file
ships in [`systemd/looki-mcp.service`](systemd/looki-mcp.service). Defaults
assume `/services/looki-mcp` as the working directory and a `.venv` virtualenv
inside that directory; adjust the paths and `User`/`Group` to match your setup.

```bash
# Place repo under /services
sudo mkdir -p /services
sudo chown $(id -un):$(id -gn) /services
git clone https://github.com/yourusername/looki-mcp /services/looki-mcp
cd /services/looki-mcp

# Set up venv + deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Configure .env (copy from .env.example, fill in your credentials)
cp .env.example .env
# edit .env

# Install + enable the unit
sudo cp systemd/looki-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now looki-mcp.service

# Check status / logs
systemctl status looki-mcp
journalctl -u looki-mcp -f
```

## Deployment (Docker)

Set your `.env`, then:

```bash
docker compose up -d        # Build and start
docker compose logs -f      # Follow logs
docker compose down         # Stop
```

Set `LOOKI_MCP_BASE_URL` to your public URL to enable the Looki icon in MCP clients:

```
LOOKI_MCP_BASE_URL=https://looki-mcp.yourdomain.com
```

## Available Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_profile` | User profile (name, email, timezone) | — |
| `get_moments_calendar` | Calendar view of active days | `start_date`, `end_date` |
| `get_moments_by_date` | All moments on a specific date | `date` |
| `get_moment_details` | Full details for one moment | `moment_id` |
| `get_moment_files` | Photos/videos from a moment | `moment_id`, `highlight`, `limit` |
| `search_moments` | Natural language memory search | `query`, `start_date`, `end_date` |
| `get_highlights` | AI-generated highlights (comics, vlogs) | `group`, `liked`, `limit` |
| `get_realtime_event` | Current real-time detection (beta) | — |
| `get_recent_activity` | Calendar summary for last N days | `days` |
| `get_todays_moments` | All moments captured today (user TZ) | — |
| `get_moment_with_media` | Moment + media in one call | `moment_id`, `highlight_only` |
| `search_moments_with_details` | Search + fetch details in one call | `query`, `max_results` |

## Health Endpoint

```
GET /health
{"status":"ok","server":"looki-mcp","version":"1.0.0","tools":12}
```

Useful for Docker healthchecks, load balancers, and uptime monitoring.

## Rate Limits

The Looki API enforces **60 requests per minute** per API key. Tools return a clear
error message when this limit is reached so the AI assistant can suggest waiting.

## Troubleshooting

**"Missing required environment variables"**
→ Ensure `.env` exists in the project directory and both `LOOKI_BASE_URL` and `LOOKI_API_KEY` are set.

**"Base URL verification failed"**
→ Copy `LOOKI_BASE_URL` exactly as shown at [web.looki.ai/api-keys](https://web.looki.ai/api-keys). Even a trailing slash mismatch will fail verification.

**"LOOKI_API_KEY must start with lk-"**
→ Verify you copied the API key, not the base URL.

**"Rate limit reached (60 requests/minute)"**
→ Wait 60 seconds. If you hit this often, reduce how often the AI calls polling tools like `get_realtime_event`.

**Icon not showing in MCP client**
→ Set `LOOKI_MCP_BASE_URL` to your public server URL (e.g. `https://looki-mcp.example.com`).
→ Confirm `/logo.ico` is accessible: `curl http://your-server:3456/logo.ico`

**`fastmcp` not found / ImportError on startup**
→ Activate your virtualenv: `source .venv/bin/activate` and re-run `pip install -r requirements.txt`.

## Project Layout

```
looki-mcp/
├── looki_mcp/             # Package
│   ├── config.py          # Env loading + base_url verification
│   ├── client.py          # httpx async client + error formatting
│   ├── models.py          # Pydantic v2 response models
│   ├── server.py          # FastMCP instance, custom routes, tool registration
│   └── tools/             # Tool definitions (one module per category)
├── assets/looki-logo.ico  # Ships with repo, served at /logo.ico
├── scripts/
│   ├── download_logo.py   # Maintenance script — re-fetch logo if Looki updates it
│   └── smoke_test.py      # Import/registration test (no .env needed)
├── main.py                # Entry point
├── requirements.txt
├── pyproject.toml
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── DECISIONS.md           # Architecture decisions
└── README.md
```

## Design Decisions

For the reasoning behind language choice, framework selection, transport mode, and
other architectural decisions, see [DECISIONS.md](./DECISIONS.md).

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feature/my-feature`
3. Run the smoke test: `python scripts/smoke_test.py`
4. Commit your changes: `git commit -m "feat: add my feature"`
5. Push and open a pull request

For significant changes, please open an issue first to discuss the approach.

## License

MIT
