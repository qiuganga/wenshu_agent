from __future__ import annotations

from typing import Any

import yaml
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.context import DataAgentContext
from app.agent.schemas.query_plan import MetricSelectionResult
from app.agent.state import DataAgentState, MetricInfoState
from app.config.app_config import app_config
from app.core.logging import logger
from app.llm.gateway import llm_gateway
from app.prompt.prompt_loader import load_prompt

METRIC_SELECTION_PARSER = PydanticOutputParser(pydantic_object=MetricSelectionResult)
llm: Any = llm_gateway


def metric_selection_format_instructions() -> str:
    return METRIC_SELECTION_PARSER.get_format_instructions()


async def _invoke_metric_selection(prompt: PromptTemplate, payload: dict[str, Any]) -> MetricSelectionResult:
    if hasattr(llm, "ainvoke_structured"):
        return await llm.ainvoke_structured(
            "filter_metric_info", payload, MetricSelectionResult, METRIC_SELECTION_PARSER
        )
    if hasattr(llm, "with_structured_output"):
        try:
            structured_llm = llm.with_structured_output(MetricSelectionResult)
            result = await structured_llm.ainvoke(payload)
            if isinstance(result, MetricSelectionResult):
                return result
            return MetricSelectionResult.model_validate(result)
        except NotImplementedError:
            pass
        except ValidationError:
            raise

    chain = prompt | llm | METRIC_SELECTION_PARSER
    return await chain.ainvoke(payload)


def _filter_selected_metrics(
    metric_infos: list[MetricInfoState],
    selection: MetricSelectionResult,
    max_metrics: int,
) -> list[MetricInfoState]:
    selected_names = set(selection.selected_metrics)
    seen_candidate_names: set[str] = set()
    filtered: list[MetricInfoState] = []
    for metric_info in metric_infos:
        metric_name = metric_info.get("name", "")
        if not metric_name or metric_name in seen_candidate_names:
            continue
        seen_candidate_names.add(metric_name)
        if metric_name not in selected_names:
            continue
        filtered.append(metric_info)
        if len(filtered) >= max_metrics:
            break
    return filtered


async def filter_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "filter_metric", "message": "Filtering metric candidates"})

    query = state["query"]
    metric_infos = state.get("metric_infos", [])
    prompt = PromptTemplate(
        template=load_prompt("filter_metric_info"),
        input_variables=["query", "metric_infos"],
        partial_variables={"format_instructions": metric_selection_format_instructions()},
    )
    selection = await _invoke_metric_selection(
        prompt,
        {"query": query, "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False)},
    )

    filtered = _filter_selected_metrics(
        metric_infos,
        selection,
        app_config.agent.max_candidate_metrics,
    )
    logger.info(f"metric filter count={len(filtered)}")
    return {"metric_infos": filtered}
