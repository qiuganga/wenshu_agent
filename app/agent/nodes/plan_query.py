from typing import Any

import yaml
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.schemas.query_plan import QueryPlan
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.llm.gateway import llm_gateway
from app.prompt.prompt_loader import load_prompt

llm: Any = llm_gateway


async def plan_query(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "plan_query", "message": "Planning structured query"})

    parser = PydanticOutputParser(pydantic_object=QueryPlan)
    payload = {
        "query": state["query"],
        "table_infos": yaml.dump(state.get("table_infos", []), allow_unicode=True, sort_keys=False),
        "metric_infos": yaml.dump(state.get("metric_infos", []), allow_unicode=True, sort_keys=False),
        "format_instructions": parser.get_format_instructions(),
    }
    if hasattr(llm, "ainvoke_structured"):
        plan = await llm.ainvoke_structured("plan_query", payload, QueryPlan, parser)
    else:
        prompt = PromptTemplate(
            template=load_prompt("plan_query"),
            input_variables=["query", "table_infos", "metric_infos"],
            partial_variables={"format_instructions": parser.get_format_instructions()},
        )
        chain = prompt | llm | parser
        plan = await chain.ainvoke(payload)
    logger.info(f"query plan generated tables={plan.tables} metrics={plan.metrics}")
    return {"query_plan": plan.model_dump()}
