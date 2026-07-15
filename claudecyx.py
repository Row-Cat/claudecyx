import logging
import os
import random
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from state import load_state, save_state

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("claudecyx")


CLAUDE_SESSION_KEY = os.getenv("CLAUDE_SESSION_KEY", "").strip()
CLAUDE_ORG_ID = os.getenv("CLAUDE_ORG_ID", "").strip()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "900"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_BACKOFF_SECONDS = int(os.getenv("MAX_BACKOFF_SECONDS", "3600"))
USER_AGENT = os.getenv(
    "CLAUDE_USER_AGENT",
    "claudecyx/1.0 (+https://github.com/cybernetics/claudecyx)",
).strip()

ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "0.90"))
CRITICAL_THRESHOLD = float(os.getenv("CRITICAL_THRESHOLD", "0.95"))
LIMIT_THRESHOLD = 1.0


class ConfigError(RuntimeError):
    pass


def validate_config() -> None:
    if not CLAUDE_SESSION_KEY:
        raise ConfigError("Missing CLAUDE_SESSION_KEY")
    if not CLAUDE_ORG_ID:
        raise ConfigError("Missing CLAUDE_ORG_ID")
    if not DISCORD_WEBHOOK_URL:
        raise ConfigError("Missing DISCORD_WEBHOOK_URL")


class AlertKind(StrEnum):
    RESET = "reset"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    message: str
    priority: str
    tags: str


def parse_usage_windows(payload: dict[str, Any]) -> dict[str, tuple[float, str | None]]:
    """Extract all relevant usage windows from the payload."""
    windows = {}
    for key, window in payload.items():
        if window is None:
            continue
        # Capture the session limit and any weekly limits
        if key == "five_hour" or key.startswith("seven_day"):
            if "utilization" not in window:
                continue

            utilization = float(window["utilization"]) / 100.0
            raw_resets = window.get("resets_at")
            resets_at = str(raw_resets) if raw_resets is not None else None

            windows[key] = (utilization, resets_at)

    return windows


def evaluate_window(
    window_name: str,
    utilization: float,
    resets_at: str | None,
    window_state: dict,
    warn_threshold: float,
    crit_threshold: float,
    limit_threshold: float,
    org_id: str,
) -> tuple[list[Alert], dict]:
    new_state = window_state.copy()
    alerts: list[Alert] = []

    # 2. No limit (limits have expired)
    if resets_at is not None and resets_at != new_state.get("last_reset_seen"):
        alerts.append(
            Alert(
                kind=AlertKind.RESET,
                message=(
                    f"[{window_name}] Limits expired/reset at {resets_at}. "
                    f"Current utilization: {utilization:.2%}"
                ),
                priority="low",
                tags="white_check_mark",
            )
        )
        new_state["last_reset_seen"] = resets_at
        new_state["alerted_warning"] = False
        new_state["alerted_critical"] = False
        new_state["alerted_limit"] = False

    # 1. At Limit
    if utilization >= limit_threshold and not new_state.get("alerted_limit"):
        alerts.append(
            Alert(
                kind=AlertKind.CRITICAL,
                message=f"[{window_name}] 🛑 AT LIMIT: 100% consumed for org {org_id}.",
                priority="max",
                tags="no_entry",
            )
        )
        new_state["alerted_limit"] = True
        new_state["alerted_critical"] = True
        new_state["alerted_warning"] = True

    # 3. At 95% of limit (Only alert if critical or limit haven't been triggered yet)
    elif (
        utilization >= crit_threshold
        and not new_state.get("alerted_critical")
        and not new_state.get("alerted_limit")
    ):
        alerts.append(
            Alert(
                kind=AlertKind.CRITICAL,
                message=f"[{window_name}] 🚨 CRITICAL usage: {utilization:.2%} consumed.",
                priority="high",
                tags="rotating_light",
            )
        )
        new_state["alerted_critical"] = True

    # 4. At 90% of limit (Only alert if warning, critical, or limit haven't been triggered yet)
    elif (
        utilization >= warn_threshold
        and not new_state.get("alerted_warning")
        and not new_state.get("alerted_critical")
        and not new_state.get("alerted_limit")
    ):
        alerts.append(
            Alert(
                kind=AlertKind.WARNING,
                message=f"[{window_name}] ⚠️ High usage: {utilization:.2%} consumed.",
                priority="default",
                tags="warning",
            )
        )
        new_state["alerted_warning"] = True

    return alerts, new_state


def send_discord_alert(message: str) -> None:
    payload = {"content": message}
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.error(
                "Failed to publish alert to Discord (%s): %s",
                resp.status_code,
                resp.text,
            )
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

    state_path = Path(os.getenv("STATE_PATH", "/data/state.json"))
    state = load_state(state_path)
    logger.info("Loaded state from %s. Tracking %d windows.", state_path, len(state.keys()))

    usage_url = f"https://claude.ai/api/organizations/{CLAUDE_ORG_ID}/usage"
    backoff_seconds = 0

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
            windows = parse_usage_windows(payload)

            # Ensure our state object is a dict
            if not isinstance(state, dict):
                state = {}

            for window_name, (utilization, resets_at) in windows.items():
                logger.info(
                    "[%s] utilization=%.4f resets_at=%s",
                    window_name,
                    utilization,
                    resets_at,
                )

                window_state = state.get(window_name, {})
                alerts, updated_window_state = evaluate_window(
                    window_name,
                    utilization,
                    resets_at,
                    window_state,
                    ALERT_THRESHOLD,
                    CRITICAL_THRESHOLD,
                    LIMIT_THRESHOLD,
                    CLAUDE_ORG_ID,
                )

                state[window_name] = updated_window_state

                for alert in alerts:
                    logger.info("Firing %s alert: %s", alert.kind.value, alert.message)
                    send_discord_alert(alert.message)

            save_state(state_path, state)

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
