import json

from app.core import query_audit
from app.core.query_audit import build_query_audit_record, log_query_audit, sql_hash


def test_query_audit_record_uses_sql_hash_and_safe_fields():
    record = build_query_audit_record(
        normalized_sql="select password from fact_order",
        referenced_tables=["fact_order"],
        sql_cost={"estimated_rows": 10, "query_cost": 3.5},
        execution_time_ms=12,
        result_row_count=1,
        result_truncated=False,
        retry_count=1,
        final_status="success",
        error_code=None,
    )
    encoded = json.dumps(record, ensure_ascii=False)

    assert record["sql_hash"] == sql_hash("select password from fact_order")
    assert "select password" not in encoded
    assert record["referenced_tables"] == ["fact_order"]
    assert record["estimated_rows"] == 10
    assert record["query_cost"] == 3.5
    assert record["final_status"] == "success"


def test_query_audit_failure_does_not_raise(monkeypatch):
    class BrokenLogger:
        def info(self, message):
            raise RuntimeError("boom")

        def warning(self, message):
            raise RuntimeError("boom")

    monkeypatch.setattr(query_audit, "logger", BrokenLogger())

    log_query_audit(
        normalized_sql="select id from fact_order",
        referenced_tables=["fact_order"],
        sql_cost={},
        execution_time_ms=None,
        result_row_count=None,
        result_truncated=None,
        retry_count=0,
        final_status="failed",
        error_code="SQL_EXECUTION_FAILED",
    )
