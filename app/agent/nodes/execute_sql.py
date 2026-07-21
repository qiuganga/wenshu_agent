import asyncio
import time

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.error_policy import classify_database_error, classify_retryable_error
from app.agent.nodes._budget import effective_timeout
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.context import request_id_ctx_var
from app.core.logging import logger
from app.core.query_audit import log_query_audit


async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "execute_sql", "message": "Executing readonly SQL"})

    sql = state.get("normalized_sql") or state.get("sql", "")
    dw_mysql_repository = runtime.context["dw_mysql_repository"]
    max_rows = min(state.get("max_result_rows", app_config.agent.max_result_rows), app_config.agent.max_result_rows)
    started_at = time.perf_counter()
    try:
        timeout_seconds = effective_timeout(state, app_config.agent.query_timeout_seconds)
        execution = await asyncio.wait_for(
            dw_mysql_repository.execute_sql(
                sql,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds,
        )
        logger.info(
            f"sql executed rows={execution.row_count} truncated={execution.truncated} "
            f"tables={state.get('sql_referenced_tables', [])} sql_length={len(sql)}"
        )
        log_query_audit(
            normalized_sql=sql,
            referenced_tables=state.get("sql_referenced_tables", []),
            sql_cost=state.get("sql_cost", {}),
            execution_time_ms=execution.execution_time_ms,
            result_row_count=execution.row_count,
            result_truncated=execution.truncated,
            retry_count=state.get("retry_count", 0),
            final_status="success",
            error_code=None,
            admission_wait_ms=state.get("admission_wait_ms"),
            global_active_queries=state.get("global_active_queries"),
            user_active_queries=state.get("user_active_queries"),
            budget_exhausted=state.get("budget_exhausted"),
            dropped_sse_events=state.get("dropped_sse_events"),
            duplicate_request=state.get("duplicate_request"),
            client_disconnected=state.get("client_disconnected"),
        )
        writer(
            {
                "event": "result",
                "node": "execute_sql",
                "message": "SQL executed",
                "row_count": execution.row_count,
                "truncated": execution.truncated,
                "execution_time_ms": execution.execution_time_ms,
                "referenced_tables": state.get("sql_referenced_tables", []),
            }
        )
        return {
            "result": execution.rows,
            "result_row_count": execution.row_count,
            "result_truncated": execution.truncated,
            "execution_time_ms": execution.execution_time_ms,
            "error": None,
            "error_code": None,
            "retryable": None,
            "audit_logged": True,
        }
    except TimeoutError:
        error_code = "QUERY_EXECUTION_TIMEOUT"
        execution_time_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            f"sql execution timed out request_id={request_id_ctx_var.get()} "
            f"error_code={error_code} tables={state.get('sql_referenced_tables', [])}"
        )
        log_query_audit(
            normalized_sql=sql,
            referenced_tables=state.get("sql_referenced_tables", []),
            sql_cost=state.get("sql_cost", {}),
            execution_time_ms=execution_time_ms,
            result_row_count=None,
            result_truncated=None,
            retry_count=state.get("retry_count", 0),
            final_status="failed",
            error_code=error_code,
            admission_wait_ms=state.get("admission_wait_ms"),
            global_active_queries=state.get("global_active_queries"),
            user_active_queries=state.get("user_active_queries"),
            budget_exhausted=state.get("budget_exhausted"),
            dropped_sse_events=state.get("dropped_sse_events"),
            duplicate_request=state.get("duplicate_request"),
            client_disconnected=state.get("client_disconnected"),
        )
        return {
            "execution_time_ms": execution_time_ms,
            "error": "SQL execution timed out",
            "error_code": error_code,
            "retryable": classify_retryable_error(error_code),
            "audit_logged": True,
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_code = classify_database_error(exc, default_error_code="SQL_EXECUTION_FAILED")
        execution_time_ms = int((time.perf_counter() - started_at) * 1000)
        logger.warning(
            f"sql execution failed request_id={request_id_ctx_var.get()} "
            f"error_code={error_code} exception_type={type(exc).__name__} "
            f"tables={state.get('sql_referenced_tables', [])}"
        )
        log_query_audit(
            normalized_sql=sql,
            referenced_tables=state.get("sql_referenced_tables", []),
            sql_cost=state.get("sql_cost", {}),
            execution_time_ms=execution_time_ms,
            result_row_count=None,
            result_truncated=None,
            retry_count=state.get("retry_count", 0),
            final_status="failed",
            error_code=error_code,
            admission_wait_ms=state.get("admission_wait_ms"),
            global_active_queries=state.get("global_active_queries"),
            user_active_queries=state.get("user_active_queries"),
            budget_exhausted=state.get("budget_exhausted"),
            dropped_sse_events=state.get("dropped_sse_events"),
            duplicate_request=state.get("duplicate_request"),
            client_disconnected=state.get("client_disconnected"),
        )
        return {
            "execution_time_ms": execution_time_ms,
            "error": "SQL execution failed",
            "error_code": error_code,
            "retryable": classify_retryable_error(error_code),
            "audit_logged": True,
        }
