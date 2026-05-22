"""Regression tests for parse_usage().

Pre-fix bug: monitor() read payload.get("utilization", 0.0) at the top level,
but the Claude usage API returns a nested shape with utilization on a 0-100
scale under windows like "five_hour". The defaulting silently produced 0.0
forever, so no alert was ever fired.
"""

import pytest

from claudecyx import parse_usage

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


def test_real_payload_extracts_five_hour_window():
    utilization, resets_at = parse_usage(REAL_PAYLOAD)
    assert utilization == pytest.approx(0.77)
    assert resets_at == "2026-05-22T19:30:01.227766+00:00"


def test_utilization_is_scaled_from_percent_to_fraction():
    payload = {"five_hour": {"utilization": 100.0, "resets_at": None}}
    utilization, _ = parse_usage(payload)
    assert utilization == pytest.approx(1.0)


def test_zero_utilization_is_preserved():
    payload = {"five_hour": {"utilization": 0.0, "resets_at": None}}
    utilization, resets_at = parse_usage(payload)
    assert utilization == 0.0
    assert resets_at is None


def test_null_five_hour_window_returns_zero_no_reset():
    # API state where the five-hour window is not currently active.
    # This is a valid "no data" state, not a schema error — return zeros.
    payload = {"five_hour": None, "seven_day": None}
    utilization, resets_at = parse_usage(payload)
    assert utilization == 0.0
    assert resets_at is None


def test_missing_five_hour_key_raises():
    # If the API schema changes such that "five_hour" disappears,
    # we want a loud failure, not silent zeros (the original bug).
    payload = {"seven_day": None, "extra_usage": {}}
    with pytest.raises(ValueError, match="five_hour"):
        parse_usage(payload)


def test_missing_utilization_inside_window_raises():
    # Window present but malformed — also a schema mismatch worth surfacing.
    payload = {"five_hour": {"resets_at": "2026-05-22T19:30:01Z"}}
    with pytest.raises(ValueError, match="utilization"):
        parse_usage(payload)


def test_missing_resets_at_inside_window_returns_none():
    payload = {"five_hour": {"utilization": 50.0}}
    utilization, resets_at = parse_usage(payload)
    assert utilization == pytest.approx(0.5)
    assert resets_at is None
