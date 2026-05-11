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
