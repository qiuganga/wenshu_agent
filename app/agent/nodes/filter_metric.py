from __future__ import annotations

import asyncio
import time
from typing import Any

import yaml
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agent.context import DataAgentContext
from app.agent.ranking.feature_extractor import QueryRequirementExtractor
from app.agent.ranking.metric_ranker import DeterministicMetricRanker
from app.agent.ranking.models import RankingPenalties, RankingWeights
from app.agent.ranking.reranker import CandidateRerankResult, constrained_metric_selection
from app.agent.schemas.query_plan import MetricSelectionResult
from app.agent.state import DataAgentState, MetricInfoState
from app.config.app_config import app_config
from app.core.logging import logger
from app.core.telemetry import telemetry_manager
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
    ranking_config = app_config.agent.candidate_ranking
    if ranking_config.enabled and hasattr(llm, "ainvoke_structured"):
        return await _rank_and_filter_metrics(state, query, metric_infos)

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


async def _rank_and_filter_metrics(
    state: DataAgentState,
    query: str,
    metric_infos: list[MetricInfoState],
) -> dict[str, Any]:
    ranking_config = app_config.agent.candidate_ranking
    started = time.perf_counter()
    weights = RankingWeights(
        lexical=ranking_config.weights.lexical,
        alias=ranking_config.weights.alias,
        vector=ranking_config.weights.vector,
        coverage=ranking_config.weights.coverage,
        value=ranking_config.weights.value,
        metric_support=ranking_config.weights.metric_support,
        relationship=ranking_config.weights.relationship,
    )
    penalties = RankingPenalties(
        disconnected=ranking_config.penalties.disconnected,
        excessive_join=ranking_config.penalties.excessive_join,
        unsupported_metric=ranking_config.penalties.unsupported_metric,
    )
    with telemetry_manager.span(
        "ranking.feature_extract",
        {"candidate_count": len(metric_infos), "score_version": "v1"},
    ):
        requirements = QueryRequirementExtractor().extract(state)
    selected_tables = state.get("table_infos", [])
    with telemetry_manager.span(
        "ranking.metric_score",
        {"candidate_count": len(metric_infos), "score_version": "v1"},
    ):
        ranked = DeterministicMetricRanker(weights=weights, penalties=penalties).rank(
            state,
            requirements,
            metric_infos,
            selected_tables,
        )
    deterministic_top = ranked[: ranking_config.deterministic_top_k_metrics]
    deterministic_names = [feature.metric_name for feature in deterministic_top]
    selection_source = "deterministic"
    reason_codes = ["DETERMINISTIC_RANKING"]
    if ranking_config.llm_rerank_enabled and deterministic_names:
        try:
            telemetry_manager.increment_counter("candidate_rerank_total", attributes={"selection_source": "metric"})
            llm_result = await asyncio.wait_for(
                llm.ainvoke_structured(
                    "filter_metric_info",
                    {
                        "query": query,
                        "metric_infos": yaml.dump(
                            [feature.safe_summary() for feature in deterministic_top],
                            allow_unicode=True,
                            sort_keys=False,
                        ),
                        "format_instructions": CandidateRerankResult.model_json_schema(),
                    },
                    CandidateRerankResult,
                ),
                timeout=ranking_config.llm_rerank_timeout_seconds,
            )
            final_selection = constrained_metric_selection(
                deterministic_names=deterministic_names,
                max_selected=ranking_config.max_selected_metrics,
                llm_result=llm_result,
            )
        except Exception as exc:
            logger.info(f"metric rerank fallback reason={type(exc).__name__}")
            telemetry_manager.increment_counter(
                "candidate_rerank_fallback_total",
                attributes={"selection_source": "metric"},
            )
            final_selection = constrained_metric_selection(
                deterministic_names=deterministic_names,
                max_selected=ranking_config.max_selected_metrics,
                llm_result=None,
            )
        selection_source = final_selection.selection_source
        reason_codes.extend(final_selection.reason_codes)
        selected_order = final_selection.selected_metrics
    else:
        selected_order = deterministic_names[: ranking_config.max_selected_metrics]
    metric_by_name = {metric.get("name", ""): metric for metric in metric_infos if metric.get("name")}
    filtered = [metric_by_name[name] for name in selected_order if name in metric_by_name]
    telemetry_manager.increment_counter("candidate_ranking_total", attributes={"selection_source": selection_source})
    telemetry_manager.record_histogram(
        "candidate_count",
        len(deterministic_top),
        attributes={"selection_source": "metric"},
    )
    telemetry_manager.record_histogram(
        "selected_candidate_count",
        len(filtered),
        attributes={"selection_source": selection_source},
    )
    telemetry_manager.record_histogram("candidate_ranking_latency_seconds", time.perf_counter() - started)
    logger.info(f"metric filter count={len(filtered)} source={selection_source}")
    return {
        "metric_infos": filtered,
        "metric_candidate_scores": [feature.safe_summary() for feature in deterministic_top],
        "metric_selection_source": selection_source,
        "metric_selection_reason_codes": list(dict.fromkeys(reason_codes)),
    }
