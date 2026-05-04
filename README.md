# claudecyx

`claudecyx` is a lightweight Python microservice for monitoring Claude organization usage and sending alerts to `ntfy`.

## Features

- Polls `https://claude.ai/api/organizations/{ORG_ID}/usage`
- Uses `CLAUDE_SESSION_KEY` and `CLAUDE_ORG_ID` from environment variables
- Sends `ntfy` alerts when:
  - usage crosses 90% (warning)
  - usage crosses 95% (critical)
  - a new `resets_at` timestamp is detected
- Exponential backoff with jitter for `429` rate-limit responses
- Configurable `User-Agent` to reduce bot-detection issues

## Requirements

- Python 3.11+
- A valid Claude session key and organization ID
- An `ntfy` topic URL (self-hosted or public)

## Configuration

Use environment variables (or copy `.env.example` to `.env`):

- `CLAUDE_SESSION_KEY` (required)
- `CLAUDE_ORG_ID` (required)
- `NTFY_URL` (default: `https://ntfy.sh/claudecyx_alerts`)
- `POLL_INTERVAL` (default: `1800` in compose, `900` in script)
- `REQUEST_TIMEOUT` (default: `20`)
- `MAX_BACKOFF_SECONDS` (default: `3600`)
- `CLAUDE_USER_AGENT` (default: `claudecyx/1.0 (homelab)` in compose)
- `ALERT_THRESHOLD` (default: `0.90`)
- `CRITICAL_THRESHOLD` (default: `0.95`)
- `LOG_LEVEL` (default: `INFO`)

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python claudecyx.py
```

## Docker Run

```bash
docker compose up -d --build
```

The container is configured to join an external `monitor_net` network in `docker-compose.yml`, which fits a typical homelab stack layout.

## Security Notes

- Treat `CLAUDE_SESSION_KEY` as sensitive.
- Never commit real credentials.
- Keep `.env` local and use Docker secrets or your preferred secret manager where possible.
