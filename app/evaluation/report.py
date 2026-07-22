from __future__ import annotations

from dataclasses import dataclass, field
from statistics import quantiles
from typing import Any


@dataclass(frozen=True)
class EvaluationCaseResult:
    case_id: str
    success: bool
    scores: dict[str, float]
    latency_ms: int = 0
    token_cost: float = 0.0
    cache_hit: bool = False
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationReport:
    dataset_version: str
    dataset_hash: str
    cases: list[EvaluationCaseResult]

    def to_dict(self) -> dict[str, Any]:
        total_cases = len(self.cases)
        successful = sum(1 for case in self.cases if case.success)
        latencies = [case.latency_ms for case in self.cases]
        return {
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "total_cases": total_cases,
            "success_rate": successful / total_cases if total_cases else 0.0,
            "sql_accuracy": _average_score(self.cases, "table_selection_accuracy"),
            "answer_score": _average_score(self.cases, "answer_relevance"),
            "latency_p95": _p95(latencies),
            "token_cost": sum(case.token_cost for case in self.cases),
            "cache_hit_rate": sum(1 for case in self.cases if case.cache_hit) / total_cases if total_cases else 0.0,
            "cases": [
                {
                    "case_id": case.case_id,
                    "success": case.success,
                    "scores": dict(case.scores),
                    "latency_ms": case.latency_ms,
                    "cache_hit": case.cache_hit,
                    "error_code": case.error_code,
                    "metadata": dict(case.metadata),
                }
                for case in self.cases
            ],
        }


def _average_score(cases: list[EvaluationCaseResult], metric_name: str) -> float:
    values = [case.scores[metric_name] for case in cases if metric_name in case.scores]
    return sum(values) / len(values) if values else 0.0


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    if len(values) < 2:
        return values[0]
    return int(quantiles(values, n=20, method="inclusive")[18])
