from types import SimpleNamespace

import pytest

from app.agent.nodes import correct_sql as correct_sql_module
from app.agent.nodes.correct_sql import correct_sql


@pytest.mark.asyncio
async def test_correct_sql_prompt_receives_internal_context(monkeypatch):
    captured = {}

    async def fake_invoke_sql_gateway(prompt_name, payload, dialect="mysql"):
        captured["prompt_name"] = prompt_name
        captured["payload"] = payload
        return "select order_amount from fact_order"

    monkeypatch.setattr(correct_sql_module, "invoke_sql_gateway", fake_invoke_sql_gateway)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = {
        "query": "sales",
        "table_infos": [{"name": "fact_order"}],
        "metric_infos": [{"name": "GMV"}],
        "query_plan": {"intent": "aggregate", "tables": ["fact_order"]},
        "date_info": {"date": "2026-07-19"},
        "db_info": {"dialect": "mysql"},
        "sql": "select bad_column from fact_order",
        "normalized_sql": "select bad_column from fact_order",
        "sql_referenced_tables": ["fact_order"],
        "sql_referenced_columns": {"fact_order": ["bad_column"]},
        "sql_cost": {
            "rejection_reasons": ["FACT_TABLE_FULL_SCAN"],
            "warnings": ["UNKNOWN_TABLE_ROLE"],
            "table_roles": {"fact_order": "fact", "temporary_source": "unknown"},
            "estimated_rows": 1000000,
        },
        "error": "SQL validation failed",
        "error_code": "SQL_VALIDATION_FAILED",
        "validation_detail": "Unknown column 'bad_column' in 'field list'",
        "retry_count": 0,
    }

    result = await correct_sql(state, runtime)

    payload = captured["payload"]
    assert captured["prompt_name"] == "correct_sql"
    assert "query_plan" in payload
    assert "error_code" in payload
    assert "validation_detail" in payload
    assert "sql_cost" in payload
    assert "intent: aggregate" in payload["query_plan"]
    assert payload["error_code"] == "SQL_VALIDATION_FAILED"
    assert payload["validation_detail"] == "Unknown column 'bad_column' in 'field list'"
    assert "FACT_TABLE_FULL_SCAN" in payload["sql_cost"]
    assert "UNKNOWN_TABLE_ROLE" in payload["sql_cost"]
    assert "temporary_source" in payload["sql_cost"]
    assert result["sql"] == "select order_amount from fact_order"
    assert result["normalized_sql"] == ""
    assert result["sql_referenced_tables"] == []
    assert result["sql_referenced_columns"] == {}
    assert result["sql_cost"] == {}
    assert result["error"] is None
    assert result["error_code"] is None
    assert result["validation_detail"] is None
    assert result["retryable"] is None
    assert "query_plan" not in result
    assert "table_infos" not in result
