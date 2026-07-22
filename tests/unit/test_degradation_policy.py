from app.governance.degradation import DegradationPolicy


def test_degradation_policy_fails_closed_for_safety_controls() -> None:
    decision = DegradationPolicy().decide(dependency="redis", safety_control=True)

    assert decision.action == "fail_closed"
    assert decision.fail_closed is True


def test_degradation_policy_allows_optional_noop() -> None:
    decision = DegradationPolicy().decide(dependency="telemetry")

    assert decision.action == "noop"
    assert decision.fail_closed is False
