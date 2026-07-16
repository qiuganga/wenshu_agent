from app.agent.graph import route_after_database_validation, route_after_security_validation


def test_security_validation_routes_to_database_when_ok():
    assert route_after_security_validation({"error": None}) == "database_validate_sql"


def test_validation_failure_routes_to_correct_sql_before_retry_limit():
    state = {"error": "bad sql", "retry_count": 0, "max_retries": 2}
    assert route_after_database_validation(state) == "correct_sql"


def test_validation_failure_routes_to_failed_after_retry_limit():
    state = {"error": "bad sql", "retry_count": 2, "max_retries": 2}
    assert route_after_database_validation(state) == "failed"
