from state import load_state, save_state


def test_load_missing_returns_empty_dict(tmp_path):
    path = tmp_path / "missing.json"
    result = load_state(path)
    assert result == {}


def test_load_corrupt_returns_empty_dict(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    result = load_state(path)
    assert result == {}


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    original = {
        "five_hour": {
            "last_reset_seen": "2026-05-15T18:00:00Z",
            "alerted_warning": True,
            "alerted_critical": False,
        }
    }
    save_state(path, original)
    loaded = load_state(path)
    assert loaded == original