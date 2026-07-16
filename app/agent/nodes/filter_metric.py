import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def filter_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "filter_metric", "message": "Filtering metric candidates"})

    query = state["query"]
    metric_infos = state.get("metric_infos", [])
    prompt = PromptTemplate(template=load_prompt("filter_metric_info"), input_variables=["query", "metric_infos"])
    chain = prompt | llm | JsonOutputParser()
    selected = await chain.ainvoke(
        {"query": query, "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False)}
    )

    selected_names = set(selected)
    filtered = [metric for metric in metric_infos if metric["name"] in selected_names]
    filtered = filtered[: app_config.agent.max_candidate_metrics]
    logger.info(f"metric filter count={len(filtered)}")
    return {"metric_infos": filtered}
