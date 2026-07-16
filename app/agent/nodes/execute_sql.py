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
    try:
        result = await asyncio.wait_for(
            dw_mysql_repository.execute_sql(sql),
            timeout=app_config.agent.query_timeout_seconds,
        )
        logger.info(
            f"sql executed rows={len(result)} tables={state.get('sql_referenced_tables', [])} "
            f"sql_length={len(sql)}"
        )
        writer(
            {
                "event": "result",
                "node": "execute_sql",
                "message": "SQL executed",
                "row_count": len(result),
                "rows": result,
            }
        )
        return {"result": result}
    except TimeoutError as exc:
        logger.exception("sql execution timed out")
        raise SQLExecutionError("SQL execution timed out") from exc
    except Exception as exc:
        logger.exception(f"sql execution failed: {exc}")
        raise SQLExecutionError() from exc
