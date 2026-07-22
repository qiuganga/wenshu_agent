from __future__ import annotations

from app.evaluation.metrics import MetricResult


def evaluate_retrieval(retrieved: list[str], expected: list[str]) -> list[MetricResult]:
    actual = {item for item in retrieved if item}
    expected_set = {item for item in expected if item}
    recall = len(actual & expected_set) / len(expected_set) if expected_set else 1.0
    precision = len(actual & expected_set) / len(actual) if actual else (1.0 if not expected_set else 0.0)
    relevance = (recall + precision) / 2
    return [
        MetricResult("retrieval_recall", recall),
        MetricResult("retrieval_precision", precision),
        MetricResult("context_relevance", relevance),
    ]
