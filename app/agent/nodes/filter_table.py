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
from app.agent.ranking.coverage import CandidateSetCoverageCalculator
from app.agent.ranking.feature_extractor import QueryRequirementExtractor
from app.agent.ranking.models import RankingPenalties, RankingWeights
from app.agent.ranking.reranker import CandidateRerankResult, constrained_table_selection
from app.agent.ranking.table_ranker import DeterministicTableRanker
from app.agent.schemas.query_plan import TableSelectionResult
from app.agent.state import DataAgentState, TableInfoState
from app.config.app_config import app_config
from app.core.logging import logger
from app.core.telemetry import telemetry_manager
from app.llm.gateway import llm_gateway
from app.prompt.prompt_loader import load_prompt

TABLE_SELECTION_PARSER = PydanticOutputParser(pydantic_object=TableSelectionResult)
llm: Any = llm_gateway


def table_selection_format_instructions() -> str:
    return TABLE_SELECTION_PARSER.get_format_instructions()


async def _invoke_table_selection(prompt: PromptTemplate, payload: dict[str, Any]) -> TableSelectionResult:
    if hasattr(llm, "ainvoke_structured"):
        return await llm.ainvoke_structured("filter_table_info", payload, TableSelectionResult, TABLE_SELECTION_PARSER)
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
    ranking_config = app_config.agent.candidate_ranking
    if ranking_config.enabled and hasattr(llm, "ainvoke_structured"):
        return await _rank_and_filter_tables(state, query, table_infos)

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


async def _rank_and_filter_tables(
    state: DataAgentState,
    query: str,
    table_infos: list[TableInfoState],
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
        {"candidate_count": len(table_infos), "score_version": "v1"},
    ):
        requirements = QueryRequirementExtractor().extract(state)
    with telemetry_manager.span(
        "ranking.table_score",
        {"candidate_count": len(table_infos), "score_version": "v1"},
    ):
        ranked = DeterministicTableRanker(weights=weights, penalties=penalties).rank(state, requirements, table_infos)
    deterministic_top = ranked[: ranking_config.deterministic_top_k_tables]
    coverage = CandidateSetCoverageCalculator().greedy_cover(
        ranked_features=deterministic_top,
        requirements=requirements,
        max_tables=ranking_config.max_selected_tables,
    )
    deterministic_names = coverage.selected_tables or [feature.table_name for feature in deterministic_top]
    selection_source = "deterministic"
    reason_codes = list(coverage.reason_codes)
    if ranking_config.llm_rerank_enabled and deterministic_names:
        try:
            telemetry_manager.increment_counter("candidate_rerank_total", attributes={"selection_source": "table"})
            llm_result = await asyncio.wait_for(
                llm.ainvoke_structured(
                    "filter_table_info",
                    {
                        "query": query,
                        "table_infos": yaml.dump(
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
            final_selection = constrained_table_selection(
                deterministic_names=deterministic_names,
                max_selected=ranking_config.max_selected_tables,
                llm_result=llm_result,
            )
        except Exception as exc:
            logger.info(f"table rerank fallback reason={type(exc).__name__}")
            telemetry_manager.increment_counter(
                "candidate_rerank_fallback_total",
                attributes={"selection_source": "table"},
            )
            final_selection = constrained_table_selection(
                deterministic_names=deterministic_names,
                max_selected=ranking_config.max_selected_tables,
                llm_result=None,
            )
        selection_source = final_selection.selection_source
        reason_codes.extend(final_selection.reason_codes)
        selected_order = final_selection.selected_tables
    else:
        selected_order = deterministic_names[: ranking_config.max_selected_tables]
    table_by_name = {table.get("name", ""): table for table in table_infos if table.get("name")}
    filtered = [table_by_name[name] for name in selected_order if name in table_by_name]
    score_summaries = [feature.safe_summary() for feature in deterministic_top]
    telemetry_manager.increment_counter("candidate_ranking_total", attributes={"selection_source": selection_source})
    telemetry_manager.record_histogram(
        "candidate_count",
        len(deterministic_top),
        attributes={"selection_source": "table"},
    )
    telemetry_manager.record_histogram(
        "selected_candidate_count",
        len(filtered),
        attributes={"selection_source": selection_source},
    )
    telemetry_manager.record_histogram(
        "requirement_coverage_ratio",
        1.0 if not coverage.uncovered_requirements else 0.5,
        attributes={"selection_source": selection_source},
    )
    telemetry_manager.record_histogram("candidate_ranking_latency_seconds", time.perf_counter() - started)
    if coverage.uncovered_requirements:
        telemetry_manager.increment_counter(
            "candidate_partial_coverage_total",
            attributes={"selection_source": "table"},
        )
    logger.info(f"table filter count={len(filtered)} source={selection_source}")
    return {
        "table_infos": filtered,
        "table_candidate_scores": score_summaries,
        "table_selection_source": selection_source,
        "table_selection_reason_codes": list(dict.fromkeys(reason_codes)),
        "uncovered_requirement_count": len(coverage.uncovered_requirements),
        "relationship_summary": {
            "connected": True,
            "total_relationship_cost": coverage.total_relationship_cost,
            "bridge_tables": coverage.bridge_tables,
        },
    }
