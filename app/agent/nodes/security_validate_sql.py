from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.exceptions import SQLSecurityError
from app.core.logging import logger
from app.security.sql_security import ensure_select_limit, validate_readonly_sql


def _allowed_tables(state: DataAgentState) -> set[str]:
    return {table["name"] for table in state.get("table_infos", []) if table.get("name")}


async def security_validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "security_validate_sql", "message": "Validating SQL security"})

    dialect = state.get("db_info", {}).get("dialect", "mysql")
    sql = state.get("sql", "")
    allowed_tables = _allowed_tables(state)
    try:
        max_rows = state.get("max_result_rows", app_config.agent.max_result_rows)
        limited_sql = ensure_select_limit(sql, max_rows, dialect=dialect)
        validation = validate_readonly_sql(limited_sql, allowed_tables=allowed_tables, dialect=dialect)
        logger.info(
            f"sql security validated tables={validation.referenced_tables} "
            f"has_limit={validation.has_limit} sql_length={len(validation.normalized_sql)}"
        )
        writer(
            {
                "event": "sql_validated",
                "node": "security_validate_sql",
                "message": "SQL passed security validation",
                "referenced_tables": validation.referenced_tables,
            }
        )
        return {
            "normalized_sql": validation.normalized_sql,
            "sql_referenced_tables": validation.referenced_tables,
            "error": None,
            "error_code": None,
        }
    except SQLSecurityError as exc:
        logger.warning(f"sql security validation failed code={exc.code} message={exc.message}")
        return {"error": exc.message, "error_code": exc.code}
