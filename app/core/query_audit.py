from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.context import request_id_ctx_var
from app.core.logging import logger


def sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _safe_list(values: Sequence[Any] | None) -> list[str]:
    return [str(value) for value in values or []]


def _safe_cost_value(sql_cost: Mapping[str, Any], key: str) -> Any:
    value = sql_cost.get(key)
    if isinstance(value, int | float | str | bool) or value is None:
        return value
    return str(value)


def build_query_audit_record(
    *,
    normalized_sql: str,
    referenced_tables: Sequence[Any] | None,
    sql_cost: Mapping[str, Any] | None,
    execution_time_ms: int | None,
    result_row_count: int | None,
    result_truncated: bool | None,
    retry_count: int,
    final_status: str,
    error_code: str | None,
) -> dict[str, Any]:
    cost = sql_cost or {}
    return {
        "request_id": request_id_ctx_var.get(),
        "sql_hash": sql_hash(normalized_sql or ""),
        "referenced_tables": _safe_list(referenced_tables),
        "estimated_rows": _safe_cost_value(cost, "estimated_rows"),
        "query_cost": _safe_cost_value(cost, "query_cost"),
        "execution_time_ms": execution_time_ms,
        "result_row_count": result_row_count,
        "result_truncated": result_truncated,
        "retry_count": retry_count,
        "final_status": final_status,
        "error_code": error_code,
    }


def log_query_audit(**kwargs: Any) -> None:
    try:
        record = build_query_audit_record(**kwargs)
        logger.info(f"query_audit {json.dumps(record, ensure_ascii=False, sort_keys=True)}")
    except Exception:
        try:
            logger.warning("query_audit_failed")
        except Exception:
            pass
