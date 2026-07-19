from __future__ import annotations

from typing import Any

import yaml
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.schemas.query_plan import TableSelectionResult
from app.agent.state import DataAgentState, TableInfoState
from app.config.app_config import app_config
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt

TABLE_SELECTION_PARSER = PydanticOutputParser(pydantic_object=TableSelectionResult)


def table_selection_format_instructions() -> str:
    return TABLE_SELECTION_PARSER.get_format_instructions()


async def _invoke_table_selection(prompt: PromptTemplate, payload: dict[str, Any]) -> TableSelectionResult:
    if hasattr(llm, "with_structured_output"):
        try:
            structured_llm = llm.with_structured_output(TableSelectionResult)
            result = await structured_llm.ainvoke(payload)
            if isinstance(result, TableSelectionResult):
                return result
            return TableSelectionResult.model_validate(result)
        except NotImplementedError:
            pass
        except ValidationError:
            raise

    chain = prompt | llm | TABLE_SELECTION_PARSER
    return await chain.ainvoke(payload)


def _filter_selected_tables(
    table_infos: list[TableInfoState],
    selection: TableSelectionResult,
    max_tables: int,
) -> list[TableInfoState]:
    selected_names = set(selection.selected_tables)
    seen_candidate_names: set[str] = set()
    filtered: list[TableInfoState] = []
    for table_info in table_infos:
        table_name = table_info.get("name", "")
        if not table_name or table_name in seen_candidate_names:
            continue
        seen_candidate_names.add(table_name)
        if table_name not in selected_names:
            continue
        filtered.append(table_info)
        if len(filtered) >= max_tables:
            break
    return filtered


async def filter_table(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "filter_table", "message": "Filtering table candidates"})

    query = state["query"]
    table_infos = state.get("table_infos", [])
    prompt = PromptTemplate(
        template=load_prompt("filter_table_info"),
        input_variables=["query", "table_infos"],
        partial_variables={"format_instructions": table_selection_format_instructions()},
    )
    selection = await _invoke_table_selection(
        prompt,
        {"query": query, "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False)},
    )

    filtered = _filter_selected_tables(
        table_infos,
        selection,
        app_config.agent.max_candidate_tables,
    )
    logger.info(f"table filter count={len(filtered)}")
    return {"table_infos": filtered}
