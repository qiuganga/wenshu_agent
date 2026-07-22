from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ComplexityLevel(StrEnum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"
    HEAVY = "HEAVY"


@dataclass(frozen=True)
class ComplexityResult:
    complexity_level: ComplexityLevel
    reason_codes: list[str]
    estimated_llm_calls: int
    estimated_agent_steps: int
    estimated_token_range: tuple[int, int]
    estimated_handoffs: int = 0


class RequestComplexityClassifier:
    ANALYSIS_TERMS = ("分析", "对比", "比较", "趋势", "原因", "解释", "why", "compare", "trend")
    RAG_TERMS = ("文档", "知识库", "依据", "政策", "合同", "document", "rag")
    SQL_TERMS = ("查询", "统计", "销售", "订单", "金额", "sql", "count", "sum")

    def classify(
        self,
        query: str,
        *,
        estimated_tables: int = 0,
        requires_multi_agent: bool = False,
        estimated_tool_calls: int = 0,
    ) -> ComplexityResult:
        text = query.lower()
        reasons: list[str] = []
        score = 0
        if len(query) > 200:
            score += 1
            reasons.append("long_query")
        if any(term in text for term in self.SQL_TERMS):
            score += 1
            reasons.append("sql_required")
        if any(term in text for term in self.RAG_TERMS):
            score += 2
            reasons.append("rag_required")
        if any(term in text for term in self.ANALYSIS_TERMS):
            score += 2
            reasons.append("analysis_required")
        if estimated_tables >= 4:
            score += 2
            reasons.append("many_tables")
        if estimated_tool_calls >= 3:
            score += 1
            reasons.append("many_tool_calls")
        if requires_multi_agent:
            score += 3
            reasons.append("multi_agent_required")
        if score <= 0:
            level = ComplexityLevel.SIMPLE
        elif score <= 2:
            level = ComplexityLevel.STANDARD
        elif score <= 5:
            level = ComplexityLevel.COMPLEX
        else:
            level = ComplexityLevel.HEAVY
        estimated_steps = max(1, 2 + estimated_tool_calls + (2 if requires_multi_agent else 0))
        estimated_llm_calls = max(1, 1 + (1 if level in {ComplexityLevel.COMPLEX, ComplexityLevel.HEAVY} else 0))
        if requires_multi_agent:
            estimated_llm_calls += 1
        token_floor = 500 if level == ComplexityLevel.SIMPLE else 1500
        token_ceiling = {
            ComplexityLevel.SIMPLE: 2000,
            ComplexityLevel.STANDARD: 6000,
            ComplexityLevel.COMPLEX: 12000,
            ComplexityLevel.HEAVY: 24000,
        }[level]
        return ComplexityResult(
            level,
            reasons or ["conservative_default"],
            estimated_llm_calls,
            estimated_steps,
            (token_floor, token_ceiling),
            int(requires_multi_agent),
        )
