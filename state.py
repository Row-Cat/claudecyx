import json
import logging
import os
from dataclasses import asdict, dataclass
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
    try:
        raw = json.loads(path.read_text())
        return State(**raw)
    except (json.JSONDecodeError, TypeError, OSError) as exc:
        logger.warning("Failed to load state from %s: %s. Using default state.", path, exc)
        return State()


def save_state(path: Path, state: State) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(asdict(state), f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
