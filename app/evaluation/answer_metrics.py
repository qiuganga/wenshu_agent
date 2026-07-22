from __future__ import annotations

import re

from app.evaluation.metrics import MetricResult


def evaluate_answer(answer: str | None, expected_answer: str | None, context: str | None = None) -> list[MetricResult]:
    normalized_answer = _normalize(answer or "")
    normalized_expected = _normalize(expected_answer or "")
    expected_terms = set(normalized_expected.split())
    answer_terms = set(normalized_answer.split())
    if normalized_expected and normalized_expected in normalized_answer:
        relevance = 1.0
    else:
        relevance = len(answer_terms & expected_terms) / len(expected_terms) if expected_terms else 1.0
    completeness = 1.0 if normalized_expected and normalized_expected in normalized_answer else relevance
    faithfulness = _faithfulness(normalized_answer, _normalize(context or ""))
    return [
        MetricResult("answer_relevance", relevance),
        MetricResult("answer_completeness", completeness),
        MetricResult("answer_faithfulness", faithfulness),
    ]


def _faithfulness(answer: str, context: str) -> float:
    if not context or not answer:
        return 1.0
    answer_numbers = set(re.findall(r"\d+(?:\.\d+)?", answer))
    if not answer_numbers:
        return 1.0
    context_numbers = set(re.findall(r"\d+(?:\.\d+)?", context))
    return len(answer_numbers & context_numbers) / len(answer_numbers)


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())
