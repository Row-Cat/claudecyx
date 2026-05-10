import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class State:
    last_reset_seen: str | None = None
    alerted_warning: bool = False
    alerted_critical: bool = False


def load_state(path: Path) -> State:
    if not path.exists():
        return State()
    raw = json.loads(path.read_text())
    return State(**raw)
