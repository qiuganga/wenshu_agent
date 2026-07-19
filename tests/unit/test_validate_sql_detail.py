from types import SimpleNamespace

import pytest

from app.agent.nodes._validation_detail import sanitize_validation_detail
from app.agent.nodes.validate_sql import validate_sql


class FakeDWRepository:
    def __init__(self, exc):
        self.exc = exc

    async def validate_sql(self, sql):
        raise self.exc


def test_sanitize_validation_detail_keeps_sql_fix_signal_and_removes_secrets():
    detail = sanitize_validation_detail(
        RuntimeError(
            "Unknown column 'bad_column' in 'field list'; "
            "host=127.0.0.1 port=3306 user=agent password=secret passwd = abc "
            "mysql://agent:secret@127.0.0.1:3306/dw "
            'File "C:\\Users\\dev\\app.py", line 12'
        )
    )

    assert "Unknown column 'bad_column'" in detail
    assert "secret" not in detail.lower()
    assert "127.0.0.1" not in detail
    assert "mysql://" not in detail
    assert "C:\\Users" not in detail
    assert "File " not in detail


def test_sanitize_validation_detail_redacts_colon_and_equals_key_values():
    detail = sanitize_validation_detail(
        RuntimeError(
            "Unknown column 'o.order_money'; Table 'dw.fake_table' doesn't exist; "
            "Column 'id' in field list is ambiguous; syntax error near 'GROUP BY'; "
            "password: super-secret passwd = abc PWD: mixed Secret: sauce token: abc123 api_key = xyz "
            "user: agent_user username=admin host: db.internal server = mysql-prod port: 3306 "
            "where user = 'alice'"
        )
    )

    assert "Unknown column 'o.order_money'" in detail
    assert "Table 'dw.fake_table' doesn't exist" in detail
    assert "Column 'id' in field list is ambiguous" in detail
    assert "syntax error near 'GROUP BY'" in detail
    assert "where user = 'alice'" in detail
    for secret in (
        "super-secret",
        "abc ",
        "mixed",
        "sauce",
        "abc123",
        "xyz",
        "agent_user",
        "admin",
        "db.internal",
        "mysql-prod",
        "3306",
    ):
        assert secret not in detail
    assert "password: [redacted]" in detail
    assert "passwd = [redacted]" in detail
    assert "PWD: [redacted]" in detail
    assert "api_key = [redacted]" in detail
    assert "host: [redacted]" in detail
    assert len(detail) <= 500


def test_sanitize_validation_detail_limits_length():
    detail = sanitize_validation_detail(RuntimeError("Unknown column 'x'; " + "a" * 1000))

    assert "Unknown column 'x'" in detail
    assert len(detail) <= 500


@pytest.mark.asyncio
async def test_validate_sql_failure_returns_generic_error_and_sanitized_detail():
    events = []
    runtime = SimpleNamespace(
        stream_writer=events.append,
        context={
            "dw_mysql_repository": FakeDWRepository(
                RuntimeError(
                    "Unknown table 'missing_table'; "
                    "server=db.internal user=agent password=topsecret postgresql://agent:topsecret@db.internal/dw"
                )
            )
        },
    )

    result = await validate_sql({"sql": "select * from missing_table"}, runtime)

    assert result["error"] == "SQL validation failed"
    assert result["error_code"] == "SQL_VALIDATION_FAILED"
    assert result["retryable"] is True
    assert "Unknown table 'missing_table'" in result["validation_detail"]
    assert "topsecret" not in result["validation_detail"]
    assert "postgresql://" not in result["validation_detail"]
    assert all("validation_detail" not in event for event in events)
    assert all("Unknown table" not in str(event) for event in events)
