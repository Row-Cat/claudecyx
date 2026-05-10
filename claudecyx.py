import logging
import os
import random
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("claudecyx")


CLAUDE_SESSION_KEY = os.getenv("CLAUDE_SESSION_KEY", "").strip()
CLAUDE_ORG_ID = os.getenv("CLAUDE_ORG_ID", "").strip()

NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh/claudecyx_alerts").strip()
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "900"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_BACKOFF_SECONDS = int(os.getenv("MAX_BACKOFF_SECONDS", "3600"))
USER_AGENT = os.getenv(
    "CLAUDE_USER_AGENT",
    "claudecyx/1.0 (+https://github.com/cybernetics/claudecyx)",
).strip()

ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "0.90"))
CRITICAL_THRESHOLD = float(os.getenv("CRITICAL_THRESHOLD", "0.95"))


class ConfigError(RuntimeError):
    pass


def validate_config() -> None:
    if not CLAUDE_SESSION_KEY:
        raise ConfigError("Missing CLAUDE_SESSION_KEY")
    if not CLAUDE_ORG_ID:
        raise ConfigError("Missing CLAUDE_ORG_ID")
    if not NTFY_URL:
        raise ConfigError("Missing NTFY_URL")


def parse_resets_at(payload: dict[str, Any]) -> str | None:
    raw = payload.get("resets_at")
    if not raw:
        return None
    if isinstance(raw, str):
        return raw
    return str(raw)


def send_alert(message: str, priority: str = "default", tags: str = "warning") -> None:
    headers = {
        "Title": "claudecyx | Claude Usage Alert",
        "Priority": priority,
        "Tags": tags,
        "User-Agent": USER_AGENT,
    }
    try:
        resp = requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.error("Failed to publish alert to ntfy (%s): %s", resp.status_code, resp.text)
    except requests.RequestException as exc:
        logger.error("Failed to publish alert: %s", exc)


def usage_headers() -> dict[str, str]:
    return {
        "Cookie": f"sessionKey={CLAUDE_SESSION_KEY}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def fetch_usage(url: str) -> requests.Response:
    return requests.get(url, headers=usage_headers(), timeout=REQUEST_TIMEOUT)


def monitor() -> None:
    validate_config()

    usage_url = f"https://claude.ai/api/organizations/{CLAUDE_ORG_ID}/usage"
    backoff_seconds = 0
    last_reset_seen: str | None = None

    while True:
        try:
            response = fetch_usage(usage_url)

            if response.status_code == 429:
                backoff_seconds = (
                    5 if backoff_seconds == 0 else min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)
                )
                jitter = random.randint(0, 3)
                sleep_for = backoff_seconds + jitter
                logger.warning("Rate limited (429). Backing off for %ss", sleep_for)
                time.sleep(sleep_for)
                continue

            backoff_seconds = 0

            if response.status_code != 200:
                logger.error(
                    "Unexpected status from Claude usage API: %s %s",
                    response.status_code,
                    response.text,
                )
                time.sleep(POLL_INTERVAL)
                continue

            payload = response.json()
            utilization = float(payload.get("utilization", 0.0))
            resets_at = parse_resets_at(payload)

            logger.info("utilization=%.4f resets_at=%s", utilization, resets_at)

            if resets_at and resets_at != last_reset_seen:
                message = (
                    f"Claude usage reset window detected at {resets_at}. "
                    f"Current utilization: {utilization:.2%}"
                )
                send_alert(
                    message,
                    priority="low",
                    tags="clock1",
                )
                last_reset_seen = resets_at

            if utilization >= CRITICAL_THRESHOLD:
                send_alert(
                    f"CRITICAL usage: {utilization:.2%} consumed for org {CLAUDE_ORG_ID}.",
                    priority="high",
                    tags="rotating_light",
                )
            elif utilization >= ALERT_THRESHOLD:
                send_alert(
                    f"High usage: {utilization:.2%} consumed for org {CLAUDE_ORG_ID}.",
                    priority="default",
                    tags="warning",
                )

        except (requests.RequestException, ValueError) as exc:
            logger.error("Polling error: %s", exc)
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)

        time.sleep(POLL_INTERVAL)


def main() -> None:
    try:
        monitor()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
