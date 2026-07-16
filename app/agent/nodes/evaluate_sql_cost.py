from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.logging import logger
from app.security.sql_cost import assess_explain_json


async def evaluate_sql_cost(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "evaluate_sql_cost", "message": "Evaluating SQL cost"})
    sql = state.get("normalized_sql") or state.get("sql", "")
    dw_mysql_repository = runtime.context["dw_mysql_repository"]
    try:
        explain_json = await dw_mysql_repository.explain_json(sql)
        assessment = assess_explain_json(
            explain_json,
            max_estimated_rows=app_config.agent.max_estimated_rows,
            max_join_tables=app_config.agent.max_join_tables,
            reject_full_table_scan=app_config.agent.reject_full_table_scan,
            reject_filesort=app_config.agent.reject_filesort,
            reject_temporary_table=app_config.agent.reject_temporary_table,
        )
        logger.info(
            f"sql cost assessed accepted={assessment.accepted} estimated_rows={assessment.estimated_rows} "
            f"table_count={assessment.table_count} reasons={assessment.rejection_reasons}"
        )
        writer(
            {
                "event": "sql_validated",
                "node": "evaluate_sql_cost",
                "message": "SQL cost evaluated",
                "estimated_rows": assessment.estimated_rows,
                "table_count": assessment.table_count,
                "accepted": assessment.accepted,
            }
        )
        if not assessment.accepted:
            return {
                "sql_cost": assessment.model_dump(),
                "error": "SQL cost too high",
                "error_code": "SQL_COST_TOO_HIGH",
            }
        return {"sql_cost": assessment.model_dump(), "error": None, "error_code": None}
    except Exception as exc:
        logger.warning(f"sql cost assessment skipped reason={type(exc).__name__}")
        if app_config.agent.reject_on_cost_error:
            return {"error": "SQL cost assessment failed", "error_code": "SQL_COST_ASSESSMENT_FAILED"}
        return {"sql_cost": {}, "error": None, "error_code": None}
