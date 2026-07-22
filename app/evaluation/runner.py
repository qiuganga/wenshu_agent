from __future__ import annotations

import json
import time
from typing import Any

from app.api.schemas.query_schema import QueryRequest
from app.core.telemetry import telemetry_manager
from app.evaluation.answer_metrics import evaluate_answer
from app.evaluation.dataset import EvaluationDataset
from app.evaluation.judge import JudgeInput, RuleJudge
from app.evaluation.rag_metrics import evaluate_retrieval
from app.evaluation.report import EvaluationCaseResult, EvaluationReport
from app.evaluation.sql_metrics import SQLEvaluationInput, evaluate_sql
from app.evaluation.trace import TraceEvaluator


class EvaluationRunner:
    def __init__(self, query_service: Any, judge: Any | None = None) -> None:
        self.query_service = query_service
        self.judge = judge or RuleJudge()
        self.trace_evaluator = TraceEvaluator()

    async def run(self, dataset: EvaluationDataset) -> EvaluationReport:
        results: list[EvaluationCaseResult] = []
        with telemetry_manager.span("evaluation.run", {"candidate_count": len(dataset.cases)}):
            for case in dataset.cases:
                started = time.perf_counter()
                with telemetry_manager.span("evaluation.case", {"resource": case.id}):
                    events = await self._run_case(case.question, case.id)
                latency_ms = int((time.perf_counter() - started) * 1000)
                result = self._evaluate_case(case, events, latency_ms)
                telemetry_manager.record_histogram("evaluation_score", _mean(result.scores.values()))
                if not result.success:
                    telemetry_manager.increment_counter("evaluation_failed_total")
                results.append(result)
        return EvaluationReport(dataset.version, dataset.dataset_hash, results)

    async def _run_case(self, question: str, case_id: str) -> list[dict[str, Any]]:
        chunks = [chunk async for chunk in self.query_service.query(QueryRequest(query=question, request_id=case_id))]
        return _parse_sse(chunks)

    def _evaluate_case(self, case: Any, events: list[dict[str, Any]], latency_ms: int) -> EvaluationCaseResult:
        final_payload = _final_payload(events)
        scores = {}
        actual_sql = str(final_payload.get("normalized_sql") or "") or None
        retrieved = _retrieved_docs(events)
        for metric in evaluate_sql(
            SQLEvaluationInput(
                actual_sql=actual_sql,
                expected_sql=case.expected_sql,
                expected_tables=case.expected_tables,
                execution_success=bool(final_payload.get("final_answer")),
            )
        ):
            scores[metric.name] = metric.bounded().score
        for metric in evaluate_retrieval(retrieved, case.expected_retrieval):
            scores[metric.name] = metric.bounded().score
        answer = str(final_payload.get("final_answer") or "")
        for metric in evaluate_answer(
            answer, case.expected_answer, context=str(final_payload.get("result_summary", {}))
        ):
            scores[metric.name] = metric.bounded().score
        with telemetry_manager.span("evaluation.judge", {"resource": case.id}):
            for metric in self.judge.evaluate(
                JudgeInput(
                    question_hash=case.to_safe_dict()["question_hash"],
                    answer=answer,
                    expected_answer=case.expected_answer,
                    safe_summary=dict(final_payload.get("result_summary", {})),
                )
            ):
                scores[f"judge_{metric.name}"] = metric.bounded().score
        for metric in self.trace_evaluator.evaluate(events):
            scores[metric.name] = metric.bounded().score
        error_code = _error_code(events)
        success = not error_code and scores.get("trace_success", 0.0) >= 1.0
        return EvaluationCaseResult(
            case_id=case.id,
            success=success,
            scores=scores,
            latency_ms=latency_ms,
            cache_hit=bool(final_payload.get("cache_hit")),
            error_code=error_code,
            metadata={"event_count": len(events)},
        )


def _parse_sse(chunks: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in chunks:
        for block in chunk.strip().split("\n\n"):
            data_lines = [line.removeprefix("data: ") for line in block.splitlines() if line.startswith("data: ")]
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
    return events


def _final_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        data = event.get("data")
        if isinstance(data, dict) and "final_answer" in data:
            return data
    return {}


def _retrieved_docs(events: list[dict[str, Any]]) -> list[str]:
    docs: list[str] = []
    for event in events:
        data = event.get("data")
        if isinstance(data, dict):
            value = data.get("retrieved_documents") or data.get("expected_retrieval")
            if isinstance(value, list):
                docs.extend(str(item) for item in value)
    return docs


def _error_code(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("event") != "error":
            continue
        data = event.get("data")
        if isinstance(data, dict):
            return str(data.get("code") or data.get("error_code") or "ERROR")
        return "ERROR"
    return None


def _mean(values: Any) -> float:
    value_list = list(values)
    return sum(value_list) / len(value_list) if value_list else 0.0
