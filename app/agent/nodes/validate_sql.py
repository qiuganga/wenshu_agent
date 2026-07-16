from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.logging import logger


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "database_validate_sql", "message": "Validating SQL with database"})

    sql = state.get("normalized_sql") or state.get("sql", "")
    dw_mysql_repository = runtime.context["dw_mysql_repository"]
    try:
        await dw_mysql_repository.validate_sql(sql)
        logger.info(f"database sql validation succeeded tables={state.get('sql_referenced_tables', [])}")
        writer({"event": "sql_validated", "node": "database_validate_sql", "message": "SQL passed database validation"})
        return {"error": None, "error_code": None}
    except Exception as exc:
        logger.exception(f"database sql validation failed: {exc}")
        return {"error": "SQL validation failed", "error_code": "SQL_VALIDATION_FAILED"}
