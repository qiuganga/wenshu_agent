from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.exceptions import SQLSecurityError
from app.core.logging import logger
from app.security.sql_security import build_sql_access_policy, enforce_select_limit, validate_readonly_sql


async def security_validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "security_validate_sql", "message": "Validating SQL security"})

    dialect = state.get("db_info", {}).get("dialect", "mysql")
    sql = state.get("sql", "")
    allowed_tables, allowed_columns = build_sql_access_policy(state.get("table_infos", []))
    try:
        max_rows = min(state.get("max_result_rows", app_config.agent.max_result_rows), app_config.agent.max_result_rows)
        limited_sql = enforce_select_limit(sql, max_rows, dialect=dialect)
        validation = validate_readonly_sql(
            limited_sql,
            allowed_tables=allowed_tables,
            allowed_columns=allowed_columns,
            dialect=dialect,
            allow_select_star=app_config.agent.allow_select_star,
            banned_functions=set(app_config.agent.banned_sql_functions),
        )
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
            "sql_referenced_columns": validation.referenced_columns,
            "error": None,
            "error_code": None,
        }
    except SQLSecurityError as exc:
        logger.warning(f"sql security validation failed code={exc.code} message={exc.message}")
        return {"error": exc.message, "error_code": exc.code}
