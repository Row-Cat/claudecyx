import pytest

from claudecyx import parse_usage_windows

REAL_PAYLOAD = {
    "five_hour": {
        "utilization": 77.0,
        "resets_at": "2026-05-22T19:30:01.227766+00:00",
    },
    "seven_day": None,
    "seven_day_oauth_apps": None,
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "seven_day_cowork": None,
    "seven_day_omelette": {
        "utilization": 41.0,
        "resets_at": "2026-05-25T00:00:00.227794+00:00",
    },
    "tangelo": None,
    "iguana_necktie": None,
    "omelette_promotional": None,
    "extra_usage": {
        "is_enabled": False,
        "monthly_limit": None,
        "used_credits": None,
        "utilization": None,
        "currency": None,
        "disabled_reason": None,
    },
}


def test_real_payload_extracts_windows():
    windows = parse_usage_windows(REAL_PAYLOAD)
    assert "five_hour" in windows
    assert "seven_day_omelette" in windows

    five_hour_util, five_hour_reset = windows["five_hour"]
    assert five_hour_util == pytest.approx(0.77)
    assert five_hour_reset == "2026-05-22T19:30:01.227766+00:00"

    seven_day_util, seven_day_reset = windows["seven_day_omelette"]
    assert seven_day_util == pytest.approx(0.41)
    assert seven_day_reset == "2026-05-25T00:00:00.227794+00:00"


def test_utilization_is_scaled_from_percent_to_fraction():
    payload = {"five_hour": {"utilization": 100.0, "resets_at": None}}
    windows = parse_usage_windows(payload)
    assert "five_hour" in windows
    assert windows["five_hour"][0] == pytest.approx(1.0)


def test_zero_utilization_is_preserved():
    payload = {"five_hour": {"utilization": 0.0, "resets_at": None}}
    windows = parse_usage_windows(payload)
    assert windows["five_hour"] == (0.0, None)


def test_null_windows_are_skipped():
    payload = {"five_hour": None, "seven_day": None}
    windows = parse_usage_windows(payload)
    assert windows == {}


def test_missing_windows_return_empty_dict():
    payload = {"extra_usage": {}}
    windows = parse_usage_windows(payload)
    assert windows == {}


def test_missing_utilization_inside_window_is_skipped():
    payload = {"five_hour": {"resets_at": "2026-05-22T19:30:01Z"}}
    windows = parse_usage_windows(payload)
    assert windows == {}


def test_missing_resets_at_inside_window_defaults_to_none():
    payload = {"five_hour": {"utilization": 50.0}}
    windows = parse_usage_windows(payload)
    assert windows["five_hour"] == (0.5, None)