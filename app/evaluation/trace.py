from __future__ import annotations

from app.evaluation.metrics import MetricResult


class TraceEvaluator:
    def evaluate(self, events: list[dict]) -> list[MetricResult]:
        event_names = [str(event.get("event", "")) for event in events]
        has_final = "result" in event_names or "final" in event_names
        has_error = "error" in event_names
        cache_hit = any(bool((event.get("data") or {}).get("cache_hit")) for event in events)
        return [
            MetricResult("trace_success", 1.0 if has_final and not has_error else 0.0),
            MetricResult("trace_cache_hit", 1.0 if cache_hit else 0.0),
            MetricResult("trace_error_free", 0.0 if has_error else 1.0),
        ]
