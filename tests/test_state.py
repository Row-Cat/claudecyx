import logging  # noqa: F401

from state import State, load_state


def test_load_missing_returns_default_state(tmp_path):
    path = tmp_path / "missing.json"
    result = load_state(path)
    assert result == State()
    assert result.last_reset_seen is None
    assert result.alerted_warning is False
    assert result.alerted_critical is False
