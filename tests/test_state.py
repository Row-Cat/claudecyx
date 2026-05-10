import logging

from state import State, load_state


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
