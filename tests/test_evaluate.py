from claudecyx import evaluate
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
