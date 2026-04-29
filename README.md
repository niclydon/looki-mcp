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

1. Open the Looki app or go to [web.looki.ai](https://web.looki.ai)
2. Navigate to **Settings → Developer**
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
| `LOOKI_BASE_URL` | yes | Your Looki API base URL (Looki app → Settings → Developer) |
| `LOOKI_API_KEY` | yes | API key starting with `lk-` |
| `LOOKI_PORT` | no | HTTP port for the server (default: `3456`) |
| `LOOKI_MCP_BASE_URL` | no | Public URL of this server, used for icon display in MCP clients |
| `ORIGIN_SHARED_SECRET` | no | Shared secret required in the `x-origin-secret` header (TODO: not yet enforced) |

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
→ Copy `LOOKI_BASE_URL` exactly from Looki app → Settings → Developer. Even a trailing slash mismatch will fail verification.

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
