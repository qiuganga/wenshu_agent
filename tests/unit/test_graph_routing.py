from app.agent.graph import (
    route_after_cost_validation,
    route_after_database_validation,
    route_after_security_validation,
)


def test_security_validation_routes_to_database_when_ok():
    assert route_after_security_validation({"error": None}) == "database_validate_sql"


def test_validation_failure_routes_to_correct_sql_before_retry_limit():
    state = {"error": "bad sql", "error_code": "SQL_VALIDATION_FAILED", "retry_count": 0, "max_retries": 2}
    assert route_after_database_validation(state) == "correct_sql"


def test_validation_failure_routes_to_failed_after_retry_limit():
    state = {"error": "bad sql", "error_code": "SQL_VALIDATION_FAILED", "retry_count": 2, "max_retries": 2}
    assert route_after_database_validation(state) == "failed"


def test_retryable_true_routes_to_correct_sql_before_limit():
    state = {"error": "bad sql", "retryable": True, "retry_count": 1, "max_retries": 2}
    assert route_after_cost_validation(state) == "correct_sql"


def test_retryable_false_routes_to_failed():
    state = {"error": "db down", "retryable": False, "retry_count": 0, "max_retries": 2}
    assert route_after_database_validation(state) == "failed"


def test_retryable_none_uses_error_code_default_for_sql_errors():
    state = {
        "error": "bad sql",
        "error_code": "SQL_COST_TOO_HIGH",
        "retryable": None,
        "retry_count": 0,
        "max_retries": 2,
    }
    assert route_after_cost_validation(state) == "correct_sql"


def test_retryable_none_unknown_error_routes_to_failed():
    state = {"error": "unknown", "retryable": None, "retry_count": 0, "max_retries": 2}
    assert route_after_security_validation(state) == "failed"
