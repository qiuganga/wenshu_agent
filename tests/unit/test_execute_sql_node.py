import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app.agent.nodes.execute_sql import execute_sql
from app.config.app_config import app_config


class FakeExecution:
    rows = [{"id": 1}]
    row_count = 1
    truncated = False
    execution_time_ms = 12


class FakeOrig(Exception):
    def __init__(self, errno):
        super().__init__(errno, "safe")
        self.errno = errno


class FakeDWRepository:
    def __init__(self, exc=None, delay: float = 0):
        self.exc = exc
        self.delay = delay
        self.calls = []

    async def execute_sql(self, sql, max_rows=None, timeout_seconds=None):
        self.calls.append((sql, max_rows, timeout_seconds))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return FakeExecution()


def runtime_for(repo):
    events = []
    return SimpleNamespace(stream_writer=events.append, context={"dw_mysql_repository": repo}), events


@pytest.mark.asyncio
async def test_execute_sql_success_returns_existing_result_shape():
    repo = FakeDWRepository()
    runtime, events = runtime_for(repo)

    result = await execute_sql(
        {
            "normalized_sql": "select id from fact_order",
            "sql_referenced_tables": ["fact_order"],
            "max_result_rows": 10,
            "sql_cost": {"estimated_rows": 1, "query_cost": 1.5},
        },
        runtime,
    )

    assert repo.calls == [("select id from fact_order", 10, app_config.agent.query_timeout_seconds)]
    assert result["result"] == [{"id": 1}]
    assert result["result_row_count"] == 1
    assert result["result_truncated"] is False
    assert result["error"] is None
    assert result["audit_logged"] is True
    assert events[-1]["event"] == "result"


@pytest.mark.asyncio
async def test_execute_sql_timeout_returns_stable_non_retryable_error(monkeypatch):
    monkeypatch.setattr(app_config.agent, "query_timeout_seconds", 0.001)
    repo = FakeDWRepository(delay=0.05)
    runtime, _events = runtime_for(repo)

    result = await execute_sql({"normalized_sql": "select id from fact_order"}, runtime)

    assert result["error_code"] == "QUERY_EXECUTION_TIMEOUT"
    assert result["retryable"] is False
    assert result["audit_logged"] is True
    assert repo.calls == [("select id from fact_order", app_config.agent.max_result_rows, 0.001)]


@pytest.mark.asyncio
async def test_execute_sql_cancelled_error_propagates():
    repo = FakeDWRepository(exc=asyncio.CancelledError())
    runtime, _events = runtime_for(repo)

    with pytest.raises(asyncio.CancelledError):
        await execute_sql({"normalized_sql": "select id from fact_order"}, runtime)


@pytest.mark.asyncio
async def test_execute_sql_connection_error_is_non_retryable():
    repo = FakeDWRepository(exc=OperationalError("select", {}, FakeOrig(2003)))
    runtime, _events = runtime_for(repo)

    result = await execute_sql({"normalized_sql": "select id from fact_order"}, runtime)

    assert result["error_code"] == "DB_CONNECTION_FAILED"
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_execute_sql_unknown_error_is_safe_non_retryable_failure():
    repo = FakeDWRepository(exc=RuntimeError("password=secret host=127.0.0.1"))
    runtime, events = runtime_for(repo)

    result = await execute_sql({"normalized_sql": "select id from fact_order"}, runtime)

    assert result["error"] == "SQL execution failed"
    assert result["error_code"] == "SQL_EXECUTION_FAILED"
    assert result["retryable"] is False
    assert "secret" not in str(events)
