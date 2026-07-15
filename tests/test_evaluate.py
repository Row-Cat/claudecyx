from claudecyx import AlertKind, evaluate_window


def test_no_alerts_when_below_thresholds():
    alerts, new_state = evaluate_window(
        window_name="five_hour",
        utilization=0.5,
        resets_at=None,
        window_state={},
        warn_threshold=0.90,
        crit_threshold=0.95,
        limit_threshold=1.0,
        org_id="test-org",
    )
    assert alerts == []
    assert new_state == {}


def test_evaluate_returns_new_state_object_not_mutated_input():
    original = {}
    _alerts, new_state = evaluate_window("five_hour", 0.5, None, original, 0.90, 0.95, 1.0, "org")
    assert new_state is not original


def test_warning_fires_once_across_polls():
    state = {}

    # First poll over 90% — fires
    alerts, state = evaluate_window("five_hour", 0.92, None, state, 0.90, 0.95, 1.0, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.WARNING
    assert alerts[0].priority == "default"
    assert state.get("alerted_warning") is True
    assert not state.get("alerted_critical")

    # Second poll still over 90% — silent
    alerts, state = evaluate_window("five_hour", 0.93, None, state, 0.90, 0.95, 1.0, "org")
    assert alerts == []
    assert state.get("alerted_warning") is True
    assert not state.get("alerted_critical")


def test_critical_fires_once_across_polls():
    state = {}
    alerts, state = evaluate_window("five_hour", 0.96, None, state, 0.90, 0.95, 1.0, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    assert alerts[0].priority == "high"
    assert state.get("alerted_critical") is True

    alerts, state = evaluate_window("five_hour", 0.97, None, state, 0.90, 0.95, 1.0, "org")
    assert alerts == []

    # Utilization drops to warning range — still no warning alert
    alerts, state = evaluate_window("five_hour", 0.92, None, state, 0.90, 0.95, 1.0, "org")
    assert alerts == []
    assert not state.get("alerted_warning")
    assert state.get("alerted_critical") is True


def test_critical_takes_precedence_over_warning_in_single_call():
    state = {}
    alerts, state = evaluate_window("five_hour", 0.96, None, state, 0.90, 0.95, 1.0, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    assert not state.get("alerted_warning")
    assert state.get("alerted_critical") is True


def test_new_resets_at_emits_reset_alert():
    state = {}
    alerts, state = evaluate_window(
        "five_hour", 0.5, "2026-05-15T18:00:00Z", state, 0.90, 0.95, 1.0, "org"
    )
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.RESET
    assert alerts[0].priority == "low"
    assert state.get("last_reset_seen") == "2026-05-15T18:00:00Z"


def test_same_resets_at_does_not_re_emit_reset_alert():
    state = {"last_reset_seen": "2026-05-15T18:00:00Z"}
    alerts, state = evaluate_window(
        "five_hour", 0.5, "2026-05-15T18:00:00Z", state, 0.90, 0.95, 1.0, "org"
    )
    assert alerts == []


def test_resets_at_none_does_not_trigger_reset_alert():
    state = {}
    alerts, state = evaluate_window("five_hour", 0.5, None, state, 0.90, 0.95, 1.0, "org")
    assert alerts == []
    assert state.get("last_reset_seen") is None


def test_both_flags_clear_when_resets_at_changes():
    state = {
        "last_reset_seen": "2026-05-15T18:00:00Z",
        "alerted_warning": True,
        "alerted_critical": True,
    }
    alerts, state = evaluate_window(
        "five_hour", 0.92, "2026-05-22T18:00:00Z", state, 0.90, 0.95, 1.0, "org"
    )
    kinds = {a.kind for a in alerts}
    assert AlertKind.RESET in kinds
    assert AlertKind.WARNING in kinds
    assert state.get("last_reset_seen") == "2026-05-22T18:00:00Z"
    assert state.get("alerted_warning") is True
    assert state.get("alerted_critical") is False


def test_at_limit_fires_max_priority_alert():
    state = {}
    alerts, state = evaluate_window("five_hour", 1.0, None, state, 0.90, 0.95, 1.0, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    assert alerts[0].priority == "max"
    assert state.get("alerted_limit") is True
    assert state.get("alerted_critical") is True
    assert state.get("alerted_warning") is True

    # Subsequent poll at limit remains silent
    alerts, state = evaluate_window("five_hour", 1.0, None, state, 0.90, 0.95, 1.0, "org")
    assert alerts == []
