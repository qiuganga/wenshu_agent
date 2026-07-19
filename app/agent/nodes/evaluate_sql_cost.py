import asyncio

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.error_policy import classify_database_error, classify_retryable_error
from app.agent.nodes._validation_detail import sanitize_validation_detail
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.context import request_id_ctx_var
from app.core.logging import logger
from app.security.sql_cost import assess_explain_json


def _cost_summary(sql_cost: dict) -> dict:
    return {
        "accepted": sql_cost.get("accepted"),
        "estimated_rows": sql_cost.get("estimated_rows"),
        "estimated_rows_produced": sql_cost.get("estimated_rows_produced"),
        "query_cost": sql_cost.get("query_cost"),
        "table_count": sql_cost.get("table_count"),
        "full_scan_tables": sql_cost.get("full_scan_tables", []),
        "full_scan_fact_tables": sql_cost.get("full_scan_fact_tables", []),
        "uses_filesort": sql_cost.get("uses_filesort"),
        "uses_temporary_table": sql_cost.get("uses_temporary_table"),
        "rejection_reasons": sql_cost.get("rejection_reasons", []),
    }


async def evaluate_sql_cost(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "evaluate_sql_cost", "message": "Evaluating SQL cost"})
    sql = state.get("normalized_sql") or state.get("sql", "")
    dw_mysql_repository = runtime.context["dw_mysql_repository"]
    try:
        explain_json = await asyncio.wait_for(
            dw_mysql_repository.explain_json(sql, timeout_seconds=app_config.agent.explain_timeout_seconds),
            timeout=app_config.agent.explain_timeout_seconds,
        )
        assessment = assess_explain_json(
            explain_json,
            table_infos=state.get("table_infos", []),
            max_estimated_rows=app_config.agent.max_estimated_rows,
            max_query_cost=app_config.agent.max_query_cost,
            max_join_tables=app_config.agent.max_join_tables,
            max_full_scan_fact_tables=app_config.agent.max_full_scan_fact_tables,
            allow_dimension_full_scan=app_config.agent.allow_dimension_full_scan,
            reject_full_table_scan=app_config.agent.reject_full_table_scan,
            reject_filesort=app_config.agent.reject_filesort,
            reject_temporary_table=app_config.agent.reject_temporary_table,
        )
        sql_cost = assessment.model_dump()
        logger.info(
            f"sql cost assessed request_id={request_id_ctx_var.get()} "
            f"accepted={assessment.accepted} estimated_rows={assessment.estimated_rows} "
            f"estimated_rows_produced={assessment.estimated_rows_produced} query_cost={assessment.query_cost} "
            f"table_count={assessment.table_count} reasons={assessment.rejection_reasons}"
        )
        writer(
            {
                "event": "sql_validated",
                "node": "evaluate_sql_cost",
                "message": "SQL cost evaluated",
                "estimated_rows": assessment.estimated_rows,
                "estimated_rows_produced": assessment.estimated_rows_produced,
                "query_cost": assessment.query_cost,
                "table_count": assessment.table_count,
                "accepted": assessment.accepted,
            }
        )
        if not assessment.accepted:
            if assessment.rejection_reasons == ["COST_ASSESSMENT_FAILED"] and not app_config.agent.reject_on_cost_error:
                return {"sql_cost": sql_cost, "error": None, "error_code": None, "retryable": None}
            error_code = (
                "SQL_COST_ASSESSMENT_FAILED"
                if assessment.rejection_reasons == ["COST_ASSESSMENT_FAILED"]
                else "SQL_COST_TOO_HIGH"
            )
            error_message = (
                "SQL cost assessment failed" if error_code == "SQL_COST_ASSESSMENT_FAILED" else "SQL cost too high"
            )
            return {
                "sql_cost": sql_cost,
                "error": error_message,
                "error_code": error_code,
                "retryable": classify_retryable_error(error_code),
            }
        return {"sql_cost": sql_cost, "error": None, "error_code": None, "retryable": None}
    except TimeoutError:
        error_code = "EXPLAIN_TIMEOUT"
        sql_cost = {
            "accepted": False,
            "estimated_rows": 0,
            "estimated_rows_produced": 0,
            "query_cost": 0.0,
            "table_count": 0,
            "full_scan_tables": [],
            "full_scan_fact_tables": [],
            "full_scan_dimension_tables": [],
            "uses_filesort": False,
            "uses_temporary_table": False,
            "rejection_reasons": [error_code],
        }
        logger.warning(
            f"sql cost assessment timed out request_id={request_id_ctx_var.get()} "
            f"error_code={error_code} cost_summary={_cost_summary(sql_cost)}"
        )
        return {
            "sql_cost": sql_cost,
            "error": "SQL cost assessment timed out",
            "error_code": error_code,
            "retryable": classify_retryable_error(error_code),
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_code = classify_database_error(exc, default_error_code="SQL_COST_ASSESSMENT_FAILED")
        validation_detail = sanitize_validation_detail(exc) if error_code == "SQL_VALIDATION_FAILED" else None
        logger.warning(
            f"sql cost assessment failed request_id={request_id_ctx_var.get()} "
            f"error_code={error_code} exception_type={type(exc).__name__}"
        )
        if error_code != "SQL_COST_ASSESSMENT_FAILED" or app_config.agent.reject_on_cost_error:
            sql_cost = {
                "accepted": False,
                "estimated_rows": 0,
                "estimated_rows_produced": 0,
                "query_cost": 0.0,
                "table_count": 0,
                "full_scan_tables": [],
                "full_scan_fact_tables": [],
                "full_scan_dimension_tables": [],
                "uses_filesort": False,
                "uses_temporary_table": False,
                "rejection_reasons": ["COST_ASSESSMENT_FAILED"],
            }
            error_message = (
                "SQL validation failed" if error_code == "SQL_VALIDATION_FAILED" else "SQL cost assessment failed"
            )
            return {
                "sql_cost": sql_cost,
                "error": error_message,
                "error_code": error_code,
                "validation_detail": validation_detail,
                "retryable": classify_retryable_error(error_code),
            }
        return {"sql_cost": {}, "error": None, "error_code": None, "retryable": None}
