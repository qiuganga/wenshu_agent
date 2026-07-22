from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.error_policy import classify_retryable_error
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.exceptions import SQLSecurityError
from app.core.logging import logger
from app.core.telemetry import telemetry_manager
from app.security.context import create_security_context
from app.security.sql_access import SQLAccessCheck, sql_access_controller
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
        access_result = None
        if app_config.security.enabled:
            database_name = state.get("db_info", {}).get("database")
            security_context = runtime.context.get("security_context") or create_security_context(
                user_id="anonymous",
                request_id=state.get("request_id", "-"),
                permissions=["agent:execute", "database:read", "table:read", "column:read"],
            )
            with telemetry_manager.span(
                "security.sql_check",
                {
                    "user_hash": security_context.user_hash,
                    "resource": "sql",
                    "action": "read",
                    "decision": "pending",
                },
            ):
                access_result = sql_access_controller.check(
                    security_context,
                    SQLAccessCheck(
                        operation=validation.statement_type,
                        tables=validation.referenced_tables,
                        columns=validation.referenced_columns,
                        database=database_name if isinstance(database_name, str) else None,
                    ),
                )
            if not access_result.allowed:
                raise SQLSecurityError(
                    "SQL access denied",
                    {
                        "permission_decision": access_result.permission_decision,
                        "denied_reason": access_result.denied_reason,
                        "denied_resource": access_result.denied_resource,
                    },
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
            "permission_decision": access_result.permission_decision if access_result else "ALLOW",
            "denied_reason": None,
            "sql_access_result": {
                "allowed": True,
                "permission_decision": access_result.permission_decision if access_result else "ALLOW",
            },
            "error": None,
            "error_code": None,
            "retryable": None,
        }
    except SQLSecurityError as exc:
        logger.warning(f"sql security validation failed code={exc.code} message={exc.message}")
        details = exc.details if isinstance(exc.details, dict) else {}
        return {
            "error": exc.message,
            "error_code": exc.code,
            "retryable": classify_retryable_error(exc.code),
            "permission_decision": details.get("permission_decision", "DENY"),
            "denied_reason": details.get("denied_reason") or exc.message,
            "sql_access_result": {
                "allowed": False,
                "permission_decision": details.get("permission_decision", "DENY"),
                "denied_reason": details.get("denied_reason") or exc.message,
            },
        }
