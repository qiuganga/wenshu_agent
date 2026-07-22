import yaml
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes._sql_output import invoke_sql_gateway, sql_format_instructions
from app.agent.state import DataAgentState
from app.core.logging import logger


async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "correct_sql", "message": "Correcting SQL"})

    retry_count = state.get("retry_count", 0) + 1
    corrected_sql = await invoke_sql_gateway(
        "correct_sql",
        {
            "query": state["query"],
            "table_infos": yaml.dump(state.get("table_infos", []), allow_unicode=True, sort_keys=False),
            "metric_infos": yaml.dump(state.get("metric_infos", []), allow_unicode=True, sort_keys=False),
            "query_plan": yaml.dump(state.get("query_plan", {}), allow_unicode=True, sort_keys=False),
            "date_info": yaml.dump(state.get("date_info", {}), allow_unicode=True, sort_keys=False),
            "db_info": yaml.dump(state.get("db_info", {}), allow_unicode=True, sort_keys=False),
            "sql": state.get("normalized_sql") or state.get("sql", ""),
            "error": state.get("error") or "SQL validation failed",
            "error_code": state.get("error_code") or "",
            "validation_detail": state.get("validation_detail") or "",
            "sql_cost": yaml.dump(state.get("sql_cost", {}), allow_unicode=True, sort_keys=False),
            "format_instructions": sql_format_instructions(),
            "previous_output": "",
            "parse_error": "",
            "correction_instruction": "",
        },
    )
    logger.info(f"sql corrected retry_count={retry_count} sql_length={len(corrected_sql)}")
    writer({"event": "sql_corrected", "node": "correct_sql", "message": "SQL corrected", "retry_count": retry_count})
    return {
        "sql": corrected_sql,
        "normalized_sql": "",
        "sql_referenced_tables": [],
        "sql_referenced_columns": {},
        "sql_cost": {},
        "retry_count": retry_count,
        "error": None,
        "error_code": None,
        "validation_detail": None,
        "retryable": None,
    }
