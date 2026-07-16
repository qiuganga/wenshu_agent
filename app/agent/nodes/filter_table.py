import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState, TableInfoState
from app.config.app_config import app_config
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def filter_table(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "filter_table", "message": "Filtering table candidates"})

    query = state["query"]
    table_infos = state.get("table_infos", [])
    prompt = PromptTemplate(template=load_prompt("filter_table_info"), input_variables=["query", "table_infos"])
    chain = prompt | llm | JsonOutputParser()
    selected = await chain.ainvoke(
        {"query": query, "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False)}
    )

    filtered: list[TableInfoState] = []
    for table_info in table_infos:
        table_name = table_info["name"]
        if table_name not in selected:
            continue
        selected_columns = set(selected[table_name])
        selected_table = TableInfoState(
            name=table_info["name"],
            role=table_info.get("role", ""),
            description=table_info.get("description", ""),
            columns=[col for col in table_info.get("columns", []) if col["name"] in selected_columns],
        )
        if selected_table["columns"]:
            filtered.append(selected_table)

    filtered = filtered[: app_config.agent.max_candidate_tables]
    logger.info(f"table filter count={len(filtered)}")
    return {"table_infos": filtered}
