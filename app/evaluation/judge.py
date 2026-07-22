from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.evaluation.answer_metrics import evaluate_answer
from app.evaluation.metrics import MetricResult


@dataclass(frozen=True)
class JudgeInput:
    question_hash: str
    answer: str
    expected_answer: str | None = None
    safe_summary: dict[str, object] = field(default_factory=dict)


class EvaluationJudge(Protocol):
    def evaluate(self, value: JudgeInput) -> list[MetricResult]: ...


class RuleJudge:
    def evaluate(self, value: JudgeInput) -> list[MetricResult]:
        return evaluate_answer(value.answer, value.expected_answer, context=str(value.safe_summary))


class LLMJudge:
    def evaluate(self, value: JudgeInput) -> list[MetricResult]:
        if _looks_sensitive(value.safe_summary):
            raise ValueError("LLM judge input contains unsafe fields")
        return RuleJudge().evaluate(value)


def _looks_sensitive(value: dict[str, object]) -> bool:
    sensitive_parts = ("password", "secret", "token", "raw_sql", "raw_result", "api_key")
    return any(any(part in str(key).lower() for part in sensitive_parts) for key in value)
