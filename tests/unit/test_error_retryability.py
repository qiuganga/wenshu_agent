import asyncio

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.agent.error_policy import classify_database_error, classify_retryable_error, failure_policy, safe_error_message


@pytest.mark.parametrize(
    "error_code",
    [
        "SQL_SECURITY_FAILED",
        "SQL_VALIDATION_FAILED",
        "SQL_COST_TOO_HIGH",
        "LLM_SQL_PARSE_FAILED",
        "LLM_SQL_SCHEMA_FAILED",
        "LLM_SQL_RETRIES_EXCEEDED",
    ],
)
def test_retryable_error_codes(error_code):
    assert classify_retryable_error(error_code) is True


@pytest.mark.parametrize(
    "error_code",
    [
        "PERMISSION_DENIED",
        "DB_CONNECTION_FAILED",
        "DATABASE_UNAVAILABLE",
        "EXPLAIN_TIMEOUT",
        "QUERY_EXECUTION_TIMEOUT",
        "SQL_COST_ASSESSMENT_FAILED",
        "SQL_EXECUTION_FAILED",
        "LLM_UNAVAILABLE",
        "INTERNAL_ERROR",
    ],
)
def test_non_retryable_error_codes(error_code):
    assert classify_retryable_error(error_code) is False


def test_unknown_error_defaults_non_retryable():
    assert classify_retryable_error("UNEXPECTED_ERROR") is False
    assert classify_retryable_error(None) is False


def test_cancelled_error_is_propagated_by_classifier():
    exc = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        classify_retryable_error(exception=exc)


def test_safe_error_message_uses_public_mapping():
    assert (
        safe_error_message("SQL_COST_TOO_HIGH")
        == "查询范围过大或执行成本过高，请缩小时间范围、减少维度或简化查询条件。"
    )
    assert safe_error_message("UNKNOWN") == "本次查询未能完成，请稍后重试或调整问题描述。"


def test_failure_policy_uses_retryable_override():
    policy = failure_policy("PERMISSION_DENIED", retryable=True)

    assert policy.error_code == "PERMISSION_DENIED"
    assert policy.retryable is True
    assert policy.user_message == "当前请求无法访问所需数据。"


class FakeOrig(Exception):
    def __init__(self, errno):
        super().__init__(errno, "safe")
        self.errno = errno


def test_database_error_classification_uses_mysql_errno_for_fixable_sql():
    exc = ProgrammingError("select", {}, FakeOrig(1054))

    assert classify_database_error(exc) == "SQL_VALIDATION_FAILED"


def test_database_error_classification_uses_mysql_errno_for_connection_failure():
    exc = OperationalError("select", {}, FakeOrig(2003))

    assert classify_database_error(exc) == "DB_CONNECTION_FAILED"


def test_database_error_classification_uses_mysql_errno_for_permission_failure():
    exc = OperationalError("select", {}, FakeOrig(1045))

    assert classify_database_error(exc) == "PERMISSION_DENIED"
