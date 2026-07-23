from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from app.agent.ranking.models import FinalMetricSelection, FinalTableSelection


class CandidateRerankResult(BaseModel):
    ordered_candidate_names: list[str] = Field(default_factory=list)
    selected_candidate_names: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RerankInput:
    names: list[str]
    bridge_names: set[str]
    max_selected: int


def constrained_table_selection(
    *,
    deterministic_names: list[str],
    max_selected: int,
    llm_result: CandidateRerankResult | None = None,
    bridge_names: set[str] | None = None,
) -> FinalTableSelection:
    bridge_names = bridge_names or set()
    if llm_result is None:
        selected = deterministic_names[:max_selected]
        return FinalTableSelection(
            selected,
            deterministic_names,
            [],
            "deterministic_fallback",
            ["DETERMINISTIC_FALLBACK"],
        )
    allowed = set(deterministic_names)
    ordered = _validated_order(llm_result.ordered_candidate_names or llm_result.selected_candidate_names, allowed)
    selected = _validated_order(llm_result.selected_candidate_names or ordered, allowed)
    for bridge in sorted(bridge_names):
        if bridge in allowed and bridge not in selected:
            selected.append(bridge)
    selected = [name for name in selected if name in allowed][:max_selected]
    if not selected:
        selected = deterministic_names[:max_selected]
        return FinalTableSelection(
            selected,
            deterministic_names,
            ordered,
            "deterministic_fallback",
            ["EMPTY_LLM_SELECTION"],
        )
    return FinalTableSelection(selected, deterministic_names, ordered, "llm_reranked", list(llm_result.reason_codes))


def constrained_metric_selection(
    *,
    deterministic_names: list[str],
    max_selected: int,
    llm_result: CandidateRerankResult | None = None,
) -> FinalMetricSelection:
    if llm_result is None:
        selected = deterministic_names[:max_selected]
        return FinalMetricSelection(
            selected,
            deterministic_names,
            [],
            "deterministic_fallback",
            ["DETERMINISTIC_FALLBACK"],
        )
    allowed = set(deterministic_names)
    ordered = _validated_order(llm_result.ordered_candidate_names or llm_result.selected_candidate_names, allowed)
    selected = _validated_order(llm_result.selected_candidate_names or ordered, allowed)[:max_selected]
    if not selected:
        selected = deterministic_names[:max_selected]
        return FinalMetricSelection(
            selected,
            deterministic_names,
            ordered,
            "deterministic_fallback",
            ["EMPTY_LLM_SELECTION"],
        )
    return FinalMetricSelection(selected, deterministic_names, ordered, "llm_reranked", list(llm_result.reason_codes))


def parse_rerank_result(value: object) -> CandidateRerankResult | None:
    try:
        if isinstance(value, CandidateRerankResult):
            return value
        return CandidateRerankResult.model_validate(value)
    except ValidationError:
        return None


def _validated_order(names: list[str], allowed: set[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in allowed or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered
