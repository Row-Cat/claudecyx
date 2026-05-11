import logging
import os
from pathlib import Path

from state import State, load_state, save_state


def test_load_missing_returns_default_state(tmp_path):
    path = tmp_path / "missing.json"
    result = load_state(path)
    assert result == State()
    assert result.last_reset_seen is None
    assert result.alerted_warning is False
    assert result.alerted_critical is False


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
