from app.governance.error_budget import ErrorBudgetManager


def test_error_budget_healthy_warning_exhausted_and_recovery() -> None:
    manager = ErrorBudgetManager(warning_ratio=0.25, exhausted_ratio=0.0, recovery_ratio=0.4)

    assert manager.evaluate(allowed_errors=100, observed_system_errors=10).status == "HEALTHY"
    assert manager.evaluate(allowed_errors=100, observed_system_errors=80).status == "WARNING"
    assert manager.evaluate(allowed_errors=100, observed_system_errors=100).status == "EXHAUSTED"
    assert manager.evaluate(allowed_errors=100, observed_system_errors=70).status == "EXHAUSTED"
    assert manager.evaluate(allowed_errors=100, observed_system_errors=50).status == "HEALTHY"
