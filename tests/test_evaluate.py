from claudecyx import AlertKind, evaluate
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


def test_warning_fires_once_across_polls():
    state = State()

    # First poll over 90% — fires
    alerts, state = evaluate(0.92, None, state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.WARNING
    assert alerts[0].priority == "default"
    assert state.alerted_warning is True
    assert state.alerted_critical is False

    # Second poll still over 90% — silent
    alerts, state = evaluate(0.93, None, state, 0.90, 0.95, "org")
    assert alerts == []
    assert state.alerted_warning is True
    assert state.alerted_critical is False


def test_critical_fires_once_across_polls():
    state = State()
    alerts, state = evaluate(0.96, None, state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    assert alerts[0].priority == "high"
    assert state.alerted_critical is True

    alerts, state = evaluate(0.97, None, state, 0.90, 0.95, "org")
    assert alerts == []

    # Utilization drops to warning range — still no alert (CRITICAL already fired this window).
    alerts, state = evaluate(0.92, None, state, 0.90, 0.95, "org")
    assert alerts == []
    assert state.alerted_warning is False
    assert state.alerted_critical is True


def test_critical_takes_precedence_over_warning_in_single_call():
    state = State()
    alerts, state = evaluate(0.96, None, state, 0.90, 0.95, "org")
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.CRITICAL
    # Critical fired; warning did NOT (mutually exclusive in one call).
    assert state.alerted_warning is False
    assert state.alerted_critical is True


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
