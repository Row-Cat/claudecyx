# State Persistence + Quality Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist alert state to disk so claudecyx fires each reset/threshold alert exactly once per reset window, and add a minimal ruff + pytest + GitHub Actions quality baseline.

**Architecture:** A new `state.py` module owns the on-disk JSON state (load + atomic save). Threshold/reset alert logic moves into a pure `evaluate()` function inside `claudecyx.py`, with `Alert` and `AlertKind` types colocated. The `monitor()` loop becomes a thin shell that fetches usage, calls `evaluate`, sends each returned alert, and saves state.

**Tech Stack:** Python 3.11, pytest, ruff, GitHub Actions, Docker.

**Source spec:** `docs/superpowers/specs/2026-05-10-state-persistence-and-quality-design.md`

---

## File Structure

**New files:**
- `state.py` — `State` dataclass, `load_state`, `save_state` (atomic write, same-dir tempfile)
- `pyproject.toml` — ruff + pytest config
- `requirements-dev.txt` — `ruff`, `pytest`
- `tests/__init__.py` — empty marker
- `tests/test_state.py` — load/save unit tests
- `tests/test_evaluate.py` — pure-function unit tests for `evaluate()`
- `.github/workflows/ci.yml` — lint + format check + tests on push/PR

**Modified files:**
- `claudecyx.py` — adds `Alert`, `AlertKind`, `evaluate()`; rewrites `monitor()` to use them + state persistence
- `Dockerfile` — pins `cyberuser` to UID 1000; creates `/data` owned by `cyberuser` before `USER` switch
- `docker-compose.yml` — adds `./data:/data` bind mount + `STATE_PATH` env
- `README.md` — adds `mkdir -p data` step + dev section

**File responsibilities:**
- `state.py` owns persistence (disk I/O, JSON encoding, atomic-write guarantee). Knows nothing about alerts or HTTP.
- `claudecyx.py` owns configuration, HTTP, alert dispatch (ntfy), the polling loop, and the pure `evaluate` decision function. Imports `State` from `state.py`.
- Tests are colocated under `tests/`. No test depends on the network.

---

## Task 1: Dev tooling + project layout

**Files:**
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `requirements-dev.txt`**

```
ruff>=0.6.0
pytest>=8.0.0
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

The `pythonpath = ["."]` line lets `tests/` import the flat `state` and `claudecyx` modules at the repo root without packaging.

- [ ] **Step 3: Create empty `tests/__init__.py`**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 4: Set up virtualenv and install deps**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Expected: clean install of `requests`, `python-dotenv`, `ruff`, `pytest`.

- [ ] **Step 5: Add `.venv/` to `.gitignore`**

Append to `.gitignore`:
```
.venv/
data/
```

(`data/` excluded because state files are per-deployment, not source-controlled.)

- [ ] **Step 6: Run `ruff format` to normalize existing code**

```bash
ruff format .
ruff check .
```

Expected: format may rewrite `claudecyx.py` slightly (quote style, trailing commas). `ruff check .` should pass with no errors.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt pyproject.toml tests/__init__.py .gitignore claudecyx.py
git commit -m "chore: add ruff + pytest tooling and tests/ skeleton"
```

---

## Task 2: `State` dataclass + `load_state` for missing file

**Files:**
- Create: `state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_state.py`:

```python
import logging

from state import State, load_state


def test_load_missing_returns_default_state(tmp_path):
    path = tmp_path / "missing.json"
    result = load_state(path)
    assert result == State()
    assert result.last_reset_seen is None
    assert result.alerted_warning is False
    assert result.alerted_critical is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_state.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `state`.

- [ ] **Step 3: Create minimal `state.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_state.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat(state): add State dataclass and load_state for missing file"
```

---

## Task 3: `load_state` handles corrupt files

**Files:**
- Modify: `state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_state.py`:

```python
def test_load_corrupt_returns_default_and_logs_warning(tmp_path, caplog):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    with caplog.at_level(logging.WARNING, logger="state"):
        result = load_state(path)
    assert result == State()
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_load_wrong_schema_returns_default(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text('{"unexpected_field": 42}')
    result = load_state(path)
    assert result == State()
```

- [ ] **Step 2: Run, expect fail**

```bash
pytest tests/test_state.py -v
```

Expected: `test_load_corrupt_returns_default_and_logs_warning` raises `json.JSONDecodeError`; `test_load_wrong_schema_returns_default` raises `TypeError` (unexpected keyword).

- [ ] **Step 3: Update `load_state` to swallow + warn**

Replace `load_state` in `state.py`:

```python
def load_state(path: Path) -> State:
    if not path.exists():
        return State()
    try:
        raw = json.loads(path.read_text())
        return State(**raw)
    except (json.JSONDecodeError, TypeError, OSError) as exc:
        logger.warning(
            "Failed to load state from %s: %s. Using default state.", path, exc
        )
        return State()
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest tests/test_state.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat(state): load_state returns defaults on corrupt/invalid files"
```

---

## Task 4: `save_state` with atomic write + same-directory tempfile

**Files:**
- Modify: `state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_state.py`:

```python
import os
from pathlib import Path

from state import save_state


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    original = State(
        last_reset_seen="2026-05-15T18:00:00Z",
        alerted_warning=True,
        alerted_critical=False,
    )
    save_state(path, original)
    loaded = load_state(path)
    assert loaded == original


def test_save_writes_tempfile_in_same_directory(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    seen_tmp_paths: list[Path] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        seen_tmp_paths.append(Path(src))
        return real_replace(src, dst)

    monkeypatch.setattr("state.os.replace", spy_replace)
    save_state(path, State(last_reset_seen="x"))
    assert len(seen_tmp_paths) == 1
    assert seen_tmp_paths[0].parent == path.parent
    assert seen_tmp_paths[0] != path
```

- [ ] **Step 2: Run, expect fail**

```bash
pytest tests/test_state.py -v
```

Expected: `ImportError: cannot import name 'save_state'`.

- [ ] **Step 3: Implement `save_state`**

Add to `state.py` (and add `import os` and `from dataclasses import asdict` at the top):

```python
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

# ... (existing State + load_state) ...


def save_state(path: Path, state: State) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(asdict(state), f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
```

The `.tmp` lives in `path.parent` (because `path.with_suffix` keeps the same parent), guaranteeing same-filesystem atomic rename.

- [ ] **Step 4: Run, expect pass**

```bash
pytest tests/test_state.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat(state): add atomic save_state with same-dir tempfile"
```

---

## Task 5: `Alert`, `AlertKind`, and `evaluate()` stub (no-alert case)

**Files:**
- Modify: `claudecyx.py`
- Create: `tests/test_evaluate.py`

- [ ] **Step 1: Add types and `evaluate` stub to `claudecyx.py`**

Add near the top of `claudecyx.py` (after existing imports, before `validate_config`):

```python
from dataclasses import dataclass
from enum import StrEnum

from state import State, load_state, save_state


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


def evaluate(
    utilization: float,
    resets_at: str | None,
    state: State,
    warn_threshold: float,
    crit_threshold: float,
    org_id: str,
) -> tuple[list[Alert], State]:
    new_state = State(
        last_reset_seen=state.last_reset_seen,
        alerted_warning=state.alerted_warning,
        alerted_critical=state.alerted_critical,
    )
    alerts: list[Alert] = []
    return alerts, new_state
```

Leave `monitor()` and the rest of the file untouched for now — wiring happens in Task 9.

- [ ] **Step 2: Write failing test**

Create `tests/test_evaluate.py`:

```python
from claudecyx import Alert, AlertKind, evaluate
from state import State


def test_no_alerts_when_below_thresholds():
    alerts, new_state = evaluate(
        utilization=0.5,
        resets_at=None,
        state=State(),
        warn_threshold=0.90,
        crit_threshold=0.95,
        org_id="test-org",
    )
    assert alerts == []
    assert new_state == State()


def test_evaluate_returns_new_state_object_not_mutated_input():
    original = State()
    _alerts, new_state = evaluate(0.5, None, original, 0.90, 0.95, "org")
    assert new_state is not original
```

- [ ] **Step 3: Run, expect pass**

```bash
pytest tests/test_evaluate.py -v
```

Expected: 2 passed. (The stub already returns `[]` and a fresh `State`.)

- [ ] **Step 4: Commit**

```bash
git add claudecyx.py tests/test_evaluate.py
git commit -m "feat: add Alert types and evaluate() skeleton"
```

---

## Task 6: `evaluate()` — warning rule fires once per window

**Files:**
- Modify: `claudecyx.py`
- Modify: `tests/test_evaluate.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_evaluate.py`:

```python
def test_warning_fires_once_across_polls():
    state = State()

    # First poll over 90% — fires
    alerts, state = evaluate(0.92, None, state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.WARNING
    assert alerts[0].priority == "default"
    assert state.alerted_warning is True

    # Second poll still over 90% — silent
    alerts, state = evaluate(0.93, None, state, 0.90, 0.95, "org")
    assert alerts == []
    assert state.alerted_warning is True
```

- [ ] **Step 2: Run, expect fail**

```bash
pytest tests/test_evaluate.py -v
```

Expected: first poll returns `[]` (stub), assertion `len(alerts) == 1` fails.

- [ ] **Step 3: Add warning rule to `evaluate`**

Update `evaluate` in `claudecyx.py` — add after the `alerts: list[Alert] = []` line, before `return`:

```python
    if utilization >= warn_threshold and not new_state.alerted_warning:
        alerts.append(
            Alert(
                kind=AlertKind.WARNING,
                message=f"High usage: {utilization:.2%} consumed for org {org_id}.",
                priority="default",
                tags="warning",
            )
        )
        new_state.alerted_warning = True
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest tests/test_evaluate.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add claudecyx.py tests/test_evaluate.py
git commit -m "feat: evaluate() fires warning alert once per window"
```

---

## Task 7: `evaluate()` — critical rule with precedence over warning

**Files:**
- Modify: `claudecyx.py`
- Modify: `tests/test_evaluate.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_evaluate.py`:

```python
def test_critical_fires_once_across_polls():
    state = State()
    alerts, state = evaluate(0.96, None, state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    assert alerts[0].priority == "high"
    assert state.alerted_critical is True

    alerts, state = evaluate(0.97, None, state, 0.90, 0.95, "org")
    assert alerts == []


def test_critical_takes_precedence_over_warning_in_single_call():
    state = State()
    alerts, state = evaluate(0.96, None, state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    # Critical fired; warning did NOT (mutually exclusive in one call).
    assert state.alerted_warning is False
    assert state.alerted_critical is True
```

- [ ] **Step 2: Run, expect fail**

```bash
pytest tests/test_evaluate.py -v
```

Expected: `test_critical_fires_once_across_polls` fails because at 0.96 the current rule fires `WARNING` (≥ 0.90, only rule that exists).

- [ ] **Step 3: Replace warning rule with critical-then-warning `elif`**

Update `evaluate` in `claudecyx.py`. Replace the warning-only block with:

```python
    if utilization >= crit_threshold and not new_state.alerted_critical:
        alerts.append(
            Alert(
                kind=AlertKind.CRITICAL,
                message=f"CRITICAL usage: {utilization:.2%} consumed for org {org_id}.",
                priority="high",
                tags="rotating_light",
            )
        )
        new_state.alerted_critical = True
    elif utilization >= warn_threshold and not new_state.alerted_warning:
        alerts.append(
            Alert(
                kind=AlertKind.WARNING,
                message=f"High usage: {utilization:.2%} consumed for org {org_id}.",
                priority="default",
                tags="warning",
            )
        )
        new_state.alerted_warning = True
```

- [ ] **Step 4: Run all tests, expect pass**

```bash
pytest -v
```

Expected: 5 in `test_evaluate.py` + 5 in `test_state.py` = 10 passed.

- [ ] **Step 5: Commit**

```bash
git add claudecyx.py tests/test_evaluate.py
git commit -m "feat: evaluate() critical fires once and takes precedence over warning"
```

---

## Task 8: `evaluate()` — reset window detection clears threshold flags

**Files:**
- Modify: `claudecyx.py`
- Modify: `tests/test_evaluate.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_evaluate.py`:

```python
def test_new_resets_at_emits_reset_alert():
    state = State()
    alerts, state = evaluate(0.5, "2026-05-15T18:00:00Z", state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.RESET
    assert alerts[0].priority == "low"
    assert state.last_reset_seen == "2026-05-15T18:00:00Z"


def test_same_resets_at_does_not_re_emit_reset_alert():
    state = State(last_reset_seen="2026-05-15T18:00:00Z")
    alerts, state = evaluate(0.5, "2026-05-15T18:00:00Z", state, 0.90, 0.95, "org")
    assert alerts == []


def test_resets_at_none_does_not_trigger_reset_alert():
    state = State()
    alerts, state = evaluate(0.5, None, state, 0.90, 0.95, "org")
    assert alerts == []
    assert state.last_reset_seen is None


def test_both_flags_clear_when_resets_at_changes():
    state = State(
        last_reset_seen="2026-05-15T18:00:00Z",
        alerted_warning=True,
        alerted_critical=True,
    )
    alerts, state = evaluate(0.92, "2026-05-22T18:00:00Z", state, 0.90, 0.95, "org")
    kinds = {a.kind for a in alerts}
    # Reset alert + warning alert (flags were cleared by the new window,
    # then 0.92 >= 0.90 fires warning fresh).
    assert AlertKind.RESET in kinds
    assert AlertKind.WARNING in kinds
    assert state.last_reset_seen == "2026-05-22T18:00:00Z"
    assert state.alerted_warning is True  # set fresh by the new warning fire
    assert state.alerted_critical is False  # cleared, didn't re-trigger
```

- [ ] **Step 2: Run, expect fail**

```bash
pytest tests/test_evaluate.py -v
```

Expected: all four new tests fail.

- [ ] **Step 3: Add reset rule as the FIRST rule in `evaluate`**

Update `evaluate` in `claudecyx.py`. Add this block **before** the critical/warning `if`/`elif`:

```python
    if resets_at is not None and resets_at != new_state.last_reset_seen:
        alerts.append(
            Alert(
                kind=AlertKind.RESET,
                message=(
                    f"Claude usage reset window detected at {resets_at}. "
                    f"Current utilization: {utilization:.2%}"
                ),
                priority="low",
                tags="clock1",
            )
        )
        new_state.last_reset_seen = resets_at
        new_state.alerted_warning = False
        new_state.alerted_critical = False
```

The full final `evaluate` body should now read: build `new_state` copy → reset rule → critical/warning if/elif → return.

- [ ] **Step 4: Run all tests, expect pass**

```bash
pytest -v
```

Expected: 14 passed total (5 state + 9 evaluate).

- [ ] **Step 5: Commit**

```bash
git add claudecyx.py tests/test_evaluate.py
git commit -m "feat: evaluate() emits reset alert on new window and clears threshold flags"
```

---

## Task 9: Wire `monitor()` to use state persistence and `evaluate`

**Files:**
- Modify: `claudecyx.py`

- [ ] **Step 1: Read current `monitor()` body**

Open `claudecyx.py` and locate `def monitor()`. Note the existing structure: validate config, build URL, init `backoff_seconds` and `last_reset_seen`, loop with try/except.

- [ ] **Step 2: Rewrite `monitor()`**

Replace the entire `monitor()` function with:

```python
def monitor() -> None:
    validate_config()

    state_path = Path(os.getenv("STATE_PATH", "/data/state.json"))
    state = load_state(state_path)
    logger.info(
        "Loaded state from %s: last_reset_seen=%s alerted_warning=%s alerted_critical=%s",
        state_path,
        state.last_reset_seen,
        state.alerted_warning,
        state.alerted_critical,
    )

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
            utilization = float(payload.get("utilization", 0.0))
            resets_at = parse_resets_at(payload)

            logger.info("utilization=%.4f resets_at=%s", utilization, resets_at)

            alerts, state = evaluate(
                utilization,
                resets_at,
                state,
                ALERT_THRESHOLD,
                CRITICAL_THRESHOLD,
                CLAUDE_ORG_ID,
            )
            for alert in alerts:
                logger.info("Firing %s alert: %s", alert.kind.value, alert.message)
                send_alert(alert.message, priority=alert.priority, tags=alert.tags)

            save_state(state_path, state)

        except (requests.RequestException, ValueError) as exc:
            logger.error("Polling error: %s", exc)
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)

        time.sleep(POLL_INTERVAL)
```

Also add `from pathlib import Path` to the imports if not already present.

- [ ] **Step 3: Remove the old in-memory `last_reset_seen` variable**

Confirm by reading `monitor()` that `last_reset_seen: str | None = None` and all its assignments are gone. State is now read from `state` object.

- [ ] **Step 4: Verify imports compile and tests still pass**

```bash
python -c "import claudecyx"
pytest -v
```

Expected: import succeeds with no error, 14 tests pass. (`evaluate` is now called by `monitor` too but no test exercises `monitor` directly.)

- [ ] **Step 5: Run ruff format + check**

```bash
ruff format .
ruff check .
```

Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add claudecyx.py
git commit -m "feat: monitor() loads state, calls evaluate, saves state per poll"
```

---

## Task 10: Dockerfile — UID 1000 + `/data` directory

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Update Dockerfile**

Replace the `RUN useradd` line + `USER` line with:

```dockerfile
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin cyberuser \
 && mkdir /data && chown cyberuser:cyberuser /data
USER cyberuser
```

The full Dockerfile should now read:

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY claudecyx.py state.py ./

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin cyberuser \
 && mkdir /data && chown cyberuser:cyberuser /data
USER cyberuser

CMD ["python", "claudecyx.py"]
```

Note the `COPY` line now includes `state.py` alongside `claudecyx.py`.

- [ ] **Step 2: Build image locally**

```bash
docker compose build
```

Expected: clean build, no errors.

- [ ] **Step 3: Verify `/data` permissions inside image**

```bash
docker run --rm claudecyx-claudecyx:latest ls -ld /data
```

Expected output (approximate): `drwxr-xr-x 2 cyberuser cyberuser 4096 ... /data`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): pin cyberuser to UID 1000 and create /data"
```

---

## Task 11: docker-compose.yml — volume + `STATE_PATH`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add volume and env var**

In `docker-compose.yml`, under the `claudecyx` service, add a `volumes:` block and the `STATE_PATH` env var.

The full updated file:

```yaml
services:
  claudecyx:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: claudecyx
    restart: unless-stopped
    environment:
      CLAUDE_SESSION_KEY: ${CLAUDE_SESSION_KEY}
      CLAUDE_ORG_ID: ${CLAUDE_ORG_ID}
      NTFY_URL: ${NTFY_URL:-https://ntfy.sh/claudecyx_alerts}
      POLL_INTERVAL: ${POLL_INTERVAL:-1800}
      REQUEST_TIMEOUT: ${REQUEST_TIMEOUT:-20}
      MAX_BACKOFF_SECONDS: ${MAX_BACKOFF_SECONDS:-3600}
      CLAUDE_USER_AGENT: ${CLAUDE_USER_AGENT:-claudecyx/1.0 (homelab)}
      ALERT_THRESHOLD: ${ALERT_THRESHOLD:-0.90}
      CRITICAL_THRESHOLD: ${CRITICAL_THRESHOLD:-0.95}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      STATE_PATH: /data/state.json
    volumes:
      - ./data:/data
    networks:
      - monitor_net

networks:
  monitor_net:
    external: true
```

- [ ] **Step 2: Validate compose file**

```bash
docker compose config
```

Expected: prints the resolved config without errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): bind-mount ./data and pass STATE_PATH"
```

---

## Task 12: README — data dir step + dev section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add `mkdir -p data` to Docker Run section**

In `README.md`, find the **Docker Run** section. Replace it with:

```markdown
## Docker Run

```bash
mkdir -p data           # bind-mounted to /data inside the container for state.json
docker compose up -d --build
```

The container is configured to join an external `monitor_net` network in `docker-compose.yml`, which fits a typical homelab stack layout. Alert state persists across restarts in `./data/state.json`.
```

(Note: the `mkdir` line must NOT be inside a nested code fence — match the existing formatting style of the file.)

- [ ] **Step 2: Add a Development section**

Append before "## Security Notes":

```markdown
## Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
ruff format --check .
pytest
```

CI runs the same three commands on every push and pull request.
```

- [ ] **Step 3: Add `STATE_PATH` to the configuration list**

In the **Configuration** section, add a bullet:

```
- `STATE_PATH` (default: `/data/state.json` in the container)
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document data dir, STATE_PATH, and dev workflow"
```

---

## Task 13: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow file**

```bash
mkdir -p .github/workflows
```

Then create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt
      - name: ruff check
        run: ruff check .
      - name: ruff format check
        run: ruff format --check .
      - name: pytest
        run: pytest -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint and test on push and pull request"
```

- [ ] **Step 3: Push to remote**

```bash
git push origin main
```

- [ ] **Step 4: Verify the CI run**

```bash
gh run watch
```

Or visit `https://github.com/Row-Cat/claudecyx/actions`. Expected: green check on the `CI` workflow.

If CI fails: read the failed step's logs, fix locally, recommit, push, repeat. Most likely failure mode is a ruff format diff that wasn't applied locally — `ruff format .` and recommit.

---

## Task 14: Final verification

**Files:** none

- [ ] **Step 1: Run the full local check one more time**

```bash
source .venv/bin/activate
ruff check .
ruff format --check .
pytest -v
```

Expected: all three clean, 14 tests passing.

- [ ] **Step 2: Confirm CI is green on `main`**

```bash
gh run list --workflow=ci.yml --limit=1
```

Expected: latest run shows `completed   success`.

- [ ] **Step 3: Hand off to deployment**

The spec's "Deployment notes" section documents the homelab steps (`git pull && mkdir -p data && docker compose up -d --build`). These are operator actions, not part of this plan.

---

## Self-Review Notes

**Spec coverage:** Every section of the spec maps to a task — state module (Tasks 2-4), Alert types (Task 5), `evaluate` (Tasks 5-8), `monitor` rewrite (Task 9), Dockerfile + compose (Tasks 10-11), README (Task 12), lint/CI (Tasks 1, 13), tests (built incrementally with each TDD task). The "no migration needed" decision means no migration task.

**Type consistency:** `State`, `Alert`, `AlertKind`, `evaluate`, `load_state`, `save_state`, `STATE_PATH`, UID `1000`, `/data` — all referenced consistently across tasks.

**Placeholder scan:** No TBDs, no "add error handling" hand-waves. Every code-changing step shows the code. Test code is complete and runnable.

**Risk:** Task 9 doesn't have a unit test for `monitor()` itself (the loop body still does I/O). The `evaluate` and state tests cover the new logic; the loop is exercised by manual smoke during deployment. Acceptable trade-off given the spec's "no HTTP mocks" decision.
