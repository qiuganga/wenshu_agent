import asyncio

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.exceptions import SQLExecutionError
from app.core.logging import logger


async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "execute_sql", "message": "Executing readonly SQL"})

    sql = state.get("normalized_sql") or state.get("sql", "")
    dw_mysql_repository = runtime.context["dw_mysql_repository"]
    max_rows = min(state.get("max_result_rows", app_config.agent.max_result_rows), app_config.agent.max_result_rows)
    try:
        execution = await asyncio.wait_for(
            dw_mysql_repository.execute_sql(
                sql,
                max_rows=max_rows,
                timeout_seconds=app_config.agent.query_timeout_seconds,
            ),
            timeout=app_config.agent.query_timeout_seconds,
        )
        logger.info(
            f"sql executed rows={execution.row_count} truncated={execution.truncated} "
            f"tables={state.get('sql_referenced_tables', [])} sql_length={len(sql)}"
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
        }
    except TimeoutError as exc:
        logger.exception("sql execution timed out")
        raise SQLExecutionError("SQL execution timed out") from exc
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(f"sql execution failed: {type(exc).__name__}")
        raise SQLExecutionError() from exc
