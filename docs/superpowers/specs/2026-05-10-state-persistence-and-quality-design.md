# claudecyx: State Persistence + Quality Baseline

**Date:** 2026-05-10
**Status:** Approved for implementation

## Summary

Two bundled changes:

1. **State persistence** — persist alert state to disk so container restarts don't re-fire alerts, and so each threshold/reset event fires exactly once per reset window.
2. **Quality baseline** — add ruff lint, pytest unit tests, and a GitHub Actions CI workflow.

Multi-org support is explicitly out of scope.

## Motivation

`claudecyx.py` currently keeps `last_reset_seen` in memory only, so a container restart re-fires the "reset window detected" alert. A separate latent bug: the 90% / 95% threshold alerts fire on **every poll** while utilization is above threshold (≈ every 30 min at the default `POLL_INTERVAL`), causing alert spam. Persisting state lets us fix both with one change.

No tests, no lint config, no CI is acceptable for a 160-line script — but adding a minimal baseline now catches obvious regressions in this and future changes.

## Design

### Alert behavior (locked)

One alert per (reset window, threshold level):
- **Reset alert** fires the first time we observe a `resets_at` value different from the persisted one.
- **Warning** (≥ `ALERT_THRESHOLD`, default 0.90) fires the first time we cross within a reset window, then stays silent for that level until the window rolls over.
- **Critical** (≥ `CRITICAL_THRESHOLD`, default 0.95) — same rule, tracked separately.

When a new reset window is observed, both threshold-fired flags clear.

### State module — `state.py` (new)

```python
@dataclass
class State:
    last_reset_seen: str | None = None
    alerted_warning: bool = False
    alerted_critical: bool = False

def load_state(path: Path) -> State:
    """Return State from JSON at path. If the file is missing or corrupt,
    log a warning and return default State()."""

def save_state(path: Path, state: State) -> None:
    """Atomic write: serialize state to JSON, write to a temp file in the
    SAME DIRECTORY as `path` (e.g., path.with_suffix(path.suffix + '.tmp')),
    fsync, then os.replace(tmp, path).

    The temp file MUST live on the same filesystem as `path`, otherwise
    os.replace falls back to a non-atomic copy. Writing inside path.parent
    guarantees this."""
```

Storage shape: one JSON object, ~80 bytes. Path comes from new env var `STATE_PATH` (default `/data/state.json`).

### Alert type

Small dataclass colocated with `evaluate` in `claudecyx.py`:

```python
class AlertKind(StrEnum):
    RESET = "reset"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    message: str
    priority: str   # ntfy priority: "low" | "default" | "high"
    tags: str       # ntfy tags string
```

### Pure decision function — `evaluate()`

No I/O, no logging. The caller is responsible for both.

```python
def evaluate(
    utilization: float,
    resets_at: str | None,
    state: State,
    warn_threshold: float,
    crit_threshold: float,
    org_id: str,
) -> tuple[list[Alert], State]:
    """Decide which alerts to fire given the current observation and prior
    state. Returns alerts to send (possibly empty) and the new state."""
```

Decision rules. Build a `new_state` as a copy of `state`, then apply in order (each step reads and writes `new_state`):

1. If `resets_at` is non-None and differs from `new_state.last_reset_seen`:
   - Append a `RESET` alert.
   - Set `new_state.last_reset_seen = resets_at`.
   - Set `new_state.alerted_warning = False` and `new_state.alerted_critical = False`.
2. If `utilization >= crit_threshold` and `new_state.alerted_critical` is False:
   - Append a `CRITICAL` alert.
   - Set `new_state.alerted_critical = True`.
3. Else if `utilization >= warn_threshold` and `new_state.alerted_warning` is False:
   - Append a `WARNING` alert.
   - Set `new_state.alerted_warning = True`.

`CRITICAL` and `WARNING` are mutually exclusive in a single call: when critical fires, warning does not, even if both thresholds are crossed. (The warning flag may still be set carried over from a prior call.) Return `(alerts, new_state)`; never mutate the input `state`.

### `monitor()` loop changes

```python
def monitor() -> None:
    validate_config()
    state_path = Path(os.getenv("STATE_PATH", "/data/state.json"))
    state = load_state(state_path)
    ...
    while True:
        # ... existing fetch + 429/non-200 handling unchanged ...
        payload = response.json()
        utilization = float(payload.get("utilization", 0.0))
        resets_at = parse_resets_at(payload)
        logger.info("utilization=%.4f resets_at=%s", utilization, resets_at)

        alerts, state = evaluate(
            utilization, resets_at, state,
            ALERT_THRESHOLD, CRITICAL_THRESHOLD, CLAUDE_ORG_ID,
        )
        for alert in alerts:
            logger.info("Firing %s alert: %s", alert.kind.value, alert.message)
            send_alert(alert.message, priority=alert.priority, tags=alert.tags)

        save_state(state_path, state)
        time.sleep(POLL_INTERVAL)
```

The loop owns all I/O and logging. `evaluate` is pure. State is saved every poll unconditionally — simpler than tracking dirty bits, and ~80 bytes is cheap.

### Docker

**Dockerfile** — pin `cyberuser` to UID 1000 (matches the typical first non-root user UID on Debian/Ubuntu, so host bind-mount permissions Just Work without entrypoint chown gymnastics). Create `/data` and chown it before the `USER` switch:

```dockerfile
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin cyberuser \
 && mkdir /data && chown cyberuser:cyberuser /data
USER cyberuser
```

`save_state`'s `.tmp` file lives inside `/data`, which `cyberuser` owns — no extra permission setup.

**docker-compose.yml** — add volume + env:

```yaml
volumes:
  - ./data:/data
environment:
  STATE_PATH: /data/state.json
```

**README** — add `mkdir -p data` before `docker compose up`, and a brief dev section pointing to `requirements-dev.txt` / `pytest` / `ruff`.

### Tests (pytest)

All tests are pure-function or hit a tmpdir — no HTTP mocks needed.

`tests/test_state.py`:
- `test_load_missing_returns_default_state`
- `test_save_then_load_roundtrip`
- `test_load_corrupt_returns_default_and_logs_warning`
- `test_save_writes_tempfile_in_same_directory` — verify the temp path used by `save_state` is inside `path.parent`, not `/tmp`

`tests/test_evaluate.py`:
- `test_no_alerts_when_below_thresholds`
- `test_warning_fires_once_across_polls`
- `test_critical_fires_once_across_polls`
- `test_critical_takes_precedence_over_warning_in_single_call`
- `test_both_flags_clear_when_resets_at_changes`
- `test_new_resets_at_emits_reset_alert`
- `test_resets_at_none_does_not_trigger_reset_alert`
- `test_same_resets_at_does_not_re_emit_reset_alert`

### Lint — `pyproject.toml` (new)

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

### Dev deps — `requirements-dev.txt` (new)

```
ruff
pytest
```

### CI — `.github/workflows/ci.yml` (new)

```yaml
name: CI
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest
```

## File layout

```
claudecyx/
├── claudecyx.py              # modified: load state, call evaluate, save state
├── state.py                  # new
├── pyproject.toml            # new (ruff config)
├── requirements.txt          # unchanged
├── requirements-dev.txt      # new: ruff, pytest
├── Dockerfile                # modified: UID 1000, mkdir /data
├── docker-compose.yml        # modified: ./data volume + STATE_PATH env
├── README.md                 # modified: data dir step + dev section
├── tests/
│   ├── __init__.py
│   ├── test_state.py
│   └── test_evaluate.py
└── .github/workflows/ci.yml  # new
```

## Out of scope

- Multi-org support. Code still assumes one org per process.
- Threshold cooldown or re-alert decay. "Once per reset window" is final.
- Metrics endpoint, health check, log rotation.
- Migration from old in-memory state. New deploy starts with empty state file. Worst case is one extra reset alert on first deploy after upgrade — acceptable.

## Deployment notes

On the homelab host (`192.168.0.56`, `~/claudecyx`) after merge:

1. `git pull`
2. `mkdir -p data`
3. `docker compose up -d --build`
4. Confirm with `docker compose logs -f claudecyx` that startup loads state and polling resumes.
5. Optional smoke test: set `ALERT_THRESHOLD=0.0` in `.env`, `docker compose up -d`, verify exactly one warning alert is sent, restore the threshold, recreate.
