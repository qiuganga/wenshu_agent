import yaml
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes._sql_output import invoke_sql_chain, sql_format_instructions
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "correct_sql", "message": "Correcting SQL"})

    retry_count = state.get("retry_count", 0) + 1
    prompt = PromptTemplate(
        template=load_prompt("correct_sql"),
        input_variables=[
            "query",
            "table_infos",
            "metric_infos",
            "date_info",
            "db_info",
            "sql",
            "error",
            "format_instructions",
            "previous_output",
            "parse_error",
            "correction_instruction",
        ],
    )
    corrected_sql = await invoke_sql_chain(
        prompt,
        llm,
        {
            "query": state["query"],
            "table_infos": yaml.dump(state.get("table_infos", []), allow_unicode=True, sort_keys=False),
            "metric_infos": yaml.dump(state.get("metric_infos", []), allow_unicode=True, sort_keys=False),
            "date_info": yaml.dump(state.get("date_info", {}), allow_unicode=True, sort_keys=False),
            "db_info": yaml.dump(state.get("db_info", {}), allow_unicode=True, sort_keys=False),
            "sql": state.get("normalized_sql") or state.get("sql", ""),
            "error": state.get("error") or "SQL validation failed",
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
        "retry_count": retry_count,
        "error": None,
        "error_code": None,
    }
