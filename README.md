# Kindora-for-ChatGPT MCP server

A Python [FastMCP](https://gofastmcp.com) server that re-exposes Kindora's public funder and grant tools so you can add them to **ChatGPT as a custom MCP connector** (Developer mode / Apps). It is a thin proxy: every tool forwards to the live Kindora MCP endpoint and returns the result unchanged.

## Easiest install: deploy, then paste the URL into ChatGPT

ChatGPT can't run a local repo; it connects to a hosted HTTPS URL. This server needs **no API keys** (Kindora's free tier is open), so hosting it is one click, no Terminal, no `.env`.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/wayanvota/kindora-chatgpt-mcp)

1. Click the button, sign in to Render with GitHub, and approve. Render reads `render.yaml` and builds the container. First deploy takes ~2 minutes.
2. Copy the service URL Render gives you and add `/mcp` to the end, e.g. `https://kindora-chatgpt-mcp.onrender.com/mcp`.
3. In ChatGPT: **Settings -> Connectors (Apps) -> Advanced -> Developer mode**, then **Create connector**, paste the URL, choose **No authentication**, and save. Enable it from the "+" menu in any chat.

That's the whole install. (Render's free tier sleeps when idle, so the first request after a quiet spell takes 30-60 seconds to wake. Fly.io, below, stays warmer.)

## What the Kindora MCP does

Kindora is a grant-discovery platform for nonprofits. Its MCP server is a read-only, free-tier service over public **IRS 990 / 990-PF** filings and **Grants.gov** opportunities, covering 174K+ US foundations, 32K+ European funders, and 43K+ open grants. The upstream server exposes ten tools across discovery, profile, financials, and reference categories. This wrapper mirrors the nine that matter for ChatGPT (it drops the upstream `list_tools` helper, which is redundant since MCP clients enumerate tools natively).

| Tool | Purpose |
|------|---------|
| `search_funders` | Find grantmakers by name, cause area, or location |
| `search_open_grants` | Find open opportunities / RFPs by topic (foundation + government) |
| `search_funder_jobs` | Find open philanthropy jobs at foundations |
| `get_funder_profile` | Detailed profile for one foundation (by EIN) |
| `get_990_summary` | IRS 990 financial summary and trends (by EIN) |
| `get_foundation_grants` | Individual grants a foundation has made (by EIN) |
| `get_funder_stats` | Aggregate giving statistics (by EIN) |
| `get_ntee_codes` | Browse/search NTEE cause-area codes |
| `health_check` | Upstream health probe |

All tools are annotated `readOnlyHint: true`, so ChatGPT runs them without write-confirmation prompts.

## Why wrap it instead of pointing ChatGPT at Kindora directly?

ChatGPT Developer mode can connect to any remote MCP server, so a wrapper is optional. It earns its place when you want one endpoint you control: curated tool descriptions, read-only annotations, a place to add auth / rate limiting / logging, header injection for a Kindora key, or to pin a specific upstream URL. If you want none of that, you can skip this and add `https://mcp.kindora.co/mcp` to ChatGPT directly.

## Repository contents

```
.
├── server.py            # the MCP server (all nine tools)
├── requirements.txt     # runtime dependency (fastmcp)
├── pyproject.toml        # packaging + pytest config
├── test_server.py        # offline tests (no network needed)
├── Dockerfile            # container image for hosting
├── fly.toml              # one-command deploy to Fly.io
├── render.yaml           # one-click deploy to Render
├── .env.example          # configuration reference
├── .github/workflows/    # CI (runs the tests)
├── LICENSE               # MIT
└── README.md
```

## Requirements

- Python 3.10+
- A way to host a public HTTPS URL if you want to use it with ChatGPT (Docker + any host, or the included Fly/Render configs).

## Get the code

```bash
git clone https://github.com/wayanvota/kindora-chatgpt-mcp.git
cd kindora-chatgpt-mcp
pip install -r requirements.txt
```

## Run locally (stdio)

```bash
python server.py
```

Use this for local testing or to add the server to a stdio MCP client (e.g. Claude Desktop).

## Run the tests

```bash
pip install -e ".[dev]"
pytest
```

The suite is offline: it checks tool registration, the read-only annotations, and the upstream-response normalization with a stubbed client. It does not make a live call to Kindora.

## Run as a public HTTP endpoint (required for ChatGPT)

ChatGPT connects to a **publicly reachable HTTPS URL**, so the server must run with the streamable-HTTP transport behind a public host.

```bash
TRANSPORT=http HOST=0.0.0.0 PORT=8000 python server.py
# serves MCP at http://<host>:8000/mcp
```

Or with Docker:

```bash
docker build -t kindora-chatgpt-mcp .
docker run -p 8000:8000 kindora-chatgpt-mcp
```

Put it behind TLS (a reverse proxy, or a platform like Fly.io / Render / Railway / Cloud Run) so the final URL is `https://your-domain/mcp`.

### One-click hosting

This repo ships configs for two free-tier hosts that give you a public HTTPS URL:

**Fly.io** (`fly.toml`):

```bash
fly launch --no-deploy --copy-config --name <your-app>
fly deploy
# URL: https://<your-app>.fly.dev/mcp
```

**Render** (`render.yaml`): push the repo to GitHub, then in Render choose **New + -> Blueprint** and pick the repo. URL: `https://<service>.onrender.com/mcp`.

## Connect it to ChatGPT

1. Enable Developer mode: **Settings -> Connectors (Apps) -> Advanced -> Developer mode**. (Available on Plus, Pro, Business, Enterprise, and Edu plans.)
2. **Connectors -> Create / Add custom connector.**
3. Enter your public URL, e.g. `https://your-domain/mcp`.
4. Authentication: **No authentication** (this proxy and Kindora's free tier are open). Add OAuth here only if you put your own auth in front.
5. Save, then enable the connector in a chat (the "+" / tools menu in the composer).

Developer mode does **not** require the `search`/`fetch` compatibility tools that ChatGPT's Deep Research connectors need; it accepts arbitrary named tools, which is why all nine Kindora tools are exposed directly.

## Configuration

All via environment variables (see `.env.example`):

| Variable | Default | Notes |
|----------|---------|-------|
| `TRANSPORT` | `stdio` | `http` for ChatGPT |
| `HOST` | `0.0.0.0` | HTTP bind host |
| `PORT` | `8000` | HTTP port |
| `MCP_PATH` | `/mcp` | HTTP path |
| `KINDORA_MCP_URL` | `https://mcp.kindora.co/mcp` | Upstream to proxy |
| `KINDORA_API_KEY` | _(unset)_ | Forwarded as `Authorization: Bearer ...` if set |
| `KINDORA_TIMEOUT` | `60` | Upstream call timeout (seconds) |

> Confirm the upstream URL against your Kindora connector listing. If Kindora moves the endpoint, set `KINDORA_MCP_URL` and nothing else changes.

## Notes and limits

- **Read-only / public data.** Nothing here writes. Data is public IRS 990 and Grants.gov.
- **Rate limits.** Kindora's free tier is roughly 100 requests/hour for anonymous users; the proxy inherits that.
- **Country fields** in grant data reflect the recipient's HQ country, not where program work is implemented.
- **Verify before publishing facts.** Treat tool output as leads, not citations: confirm a foundation's current giving and open RFPs against the funder's own filings or site.
