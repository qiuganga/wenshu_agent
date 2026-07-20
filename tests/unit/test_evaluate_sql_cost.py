import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.agent.nodes.evaluate_sql_cost import evaluate_sql_cost
from app.config.app_config import app_config


class FakeDWRepository:
    def __init__(self, explain_json=None, exc=None, delay: float = 0):
        self.explain_json_value = explain_json or "{}"
        self.exc = exc
        self.delay = delay
        self.calls = []

    async def explain_json(self, sql, timeout_seconds=None):
        self.calls.append((sql, timeout_seconds))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.explain_json_value


class FakeOrig(Exception):
    def __init__(self, errno):
        super().__init__(errno, "safe")
        self.errno = errno


def runtime_for(repo):
    events = []
    return SimpleNamespace(stream_writer=events.append, context={"dw_mysql_repository": repo}), events


@pytest.mark.asyncio
async def test_cost_high_is_retryable_and_keeps_rejection_reasons(monkeypatch):
    monkeypatch.setattr(app_config.agent, "max_estimated_rows", 100)
    repo = FakeDWRepository(
        '{"query_block":{"table":{"table_name":"fact_order","access_type":"ref","rows_examined_per_scan":1000}}}'
    )
    runtime, events = runtime_for(repo)

    result = await evaluate_sql_cost(
        {"normalized_sql": "select order_id from fact_order", "sql_referenced_tables": ["fact_order"]},
        runtime,
    )

    assert result["error_code"] == "SQL_COST_TOO_HIGH"
    assert result["retryable"] is True
    assert result["sql_cost"]["rejection_reasons"] == ["ESTIMATED_ROWS_EXCEEDED"]
    assert result["sql_cost"]["table_roles"] == {"fact_order": "fact"}
    assert result["sql_cost"]["query_cost_source"] == "unavailable"
    assert events[-1]["accepted"] is False
    assert "query_cost_source" not in events[-1]


@pytest.mark.asyncio
async def test_explain_uses_independent_timeout(monkeypatch):
    monkeypatch.setattr(app_config.agent, "explain_timeout_seconds", 0.001)
    repo = FakeDWRepository(delay=0.05)
    runtime, events = runtime_for(repo)

    result = await evaluate_sql_cost({"normalized_sql": "select 1"}, runtime)

    assert repo.calls == [("select 1", 0.001)]
    assert result["error_code"] == "EXPLAIN_TIMEOUT"
    assert result["retryable"] is False
    assert result["sql_cost"]["rejection_reasons"] == ["EXPLAIN_TIMEOUT"]
    assert result["sql_cost"]["query_cost_source"] == "unavailable"
    assert result["sql_cost"]["full_scan_unknown_tables"] == []
    assert all("explain" not in str(event).lower() for event in events if event.get("event") != "stage")


@pytest.mark.asyncio
async def test_explain_cancelled_error_propagates():
    repo = FakeDWRepository(exc=asyncio.CancelledError())
    runtime, _events = runtime_for(repo)

    with pytest.raises(asyncio.CancelledError):
        await evaluate_sql_cost({"normalized_sql": "select 1"}, runtime)


@pytest.mark.asyncio
async def test_explain_unknown_column_is_retryable_validation_failure():
    repo = FakeDWRepository(exc=ProgrammingError("select", {}, FakeOrig(1054)))
    runtime, events = runtime_for(repo)

    result = await evaluate_sql_cost({"normalized_sql": "select missing_col from fact_order"}, runtime)

    assert result["error_code"] == "SQL_VALIDATION_FAILED"
    assert result["retryable"] is True
    assert "validation_detail" in result
    assert "missing_col" not in str(events)


@pytest.mark.asyncio
async def test_explain_connection_failure_is_non_retryable():
    repo = FakeDWRepository(exc=OperationalError("select", {}, FakeOrig(2003)))
    runtime, _events = runtime_for(repo)

    result = await evaluate_sql_cost({"normalized_sql": "select order_id from fact_order"}, runtime)

    assert result["error_code"] == "DB_CONNECTION_FAILED"
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_malformed_explain_json_is_skipped_when_cost_error_not_rejected(monkeypatch):
    monkeypatch.setattr(app_config.agent, "reject_on_cost_error", False)
    repo = FakeDWRepository("not json")
    runtime, _events = runtime_for(repo)

    result = await evaluate_sql_cost({"normalized_sql": "select 1"}, runtime)

    assert result["error"] is None
    assert result["sql_cost"]["rejection_reasons"] == ["COST_ASSESSMENT_FAILED"]


@pytest.mark.asyncio
async def test_malformed_explain_json_rejected_when_configured(monkeypatch):
    monkeypatch.setattr(app_config.agent, "reject_on_cost_error", True)
    repo = FakeDWRepository("not json")
    runtime, _events = runtime_for(repo)

    result = await evaluate_sql_cost({"normalized_sql": "select 1"}, runtime)

    assert result["error_code"] == "SQL_COST_ASSESSMENT_FAILED"
    assert result["retryable"] is False
