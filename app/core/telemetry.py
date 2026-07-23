from __future__ import annotations

import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.config.app_config import app_config
from app.core.context import execution_id_ctx_var, request_id_ctx_var, trace_id_ctx_var

try:  # pragma: no cover - exercised only when optional SDK is installed
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
except Exception:  # pragma: no cover - no SDK in the default test environment
    metrics = None
    trace = None
    MeterProvider = None
    ConsoleMetricExporter = None
    PeriodicExportingMetricReader = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None

SAFE_ATTRIBUTE_KEYS = {
    "duration_ms",
    "error_code",
    "execution_id",
    "estimated_cost",
    "fallback_used",
    "cache_entry_age_seconds",
    "cache_entry_size",
    "cache_hit",
    "cache_type",
    "candidate_count",
    "data_version",
    "input_tokens",
    "latency_ms",
    "model_name",
    "node_name",
    "output_tokens",
    "prompt_version",
    "query_hash",
    "request_id",
    "rerank_fallback",
    "rerank_used",
    "resource",
    "retry_count",
    "risk_level",
    "row_count",
    "scope_hash",
    "similarity_score",
    "score_version",
    "selected_count",
    "selection_source",
    "sql_hash",
    "table_names",
    "threshold",
    "total_tokens",
    "trace_id",
    "action",
    "decision",
    "denied_reason",
    "masking_applied",
    "permission_decision",
    "prompt_risk_level",
    "sql_access_result",
    "tool_name",
    "user_hash",
    "capability",
    "agent_name",
    "budget_status",
    "complexity_level",
    "cost_bucket",
    "error_budget_status",
    "load_shed_reason",
    "pricing_version",
    "quota_type",
    "receiver",
    "route_reason",
    "sender",
    "slo_name",
    "slo_status",
    "usage_source",
}
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "passwd",
    "prompt",
    "raw_result",
    "raw_rows",
    "response",
    "result_data",
    "secret",
    "sql",
    "token",
)
SQL_PREFIXES = ("select ", "insert ", "update ", "delete ", "with ", "explain ")


@dataclass
class CapturedSpan:
    name: str
    attributes: dict[str, Any]
    status: str = "ok"
    duration_ms: int = 0


@dataclass
class CapturedMetric:
    name: str
    value: int | float
    attributes: dict[str, Any] = field(default_factory=dict)


class _NoopInstrument:
    def add(self, value: int | float, attributes: Mapping[str, Any] | None = None) -> None:
        return None

    def record(self, value: int | float, attributes: Mapping[str, Any] | None = None) -> None:
        return None


class TelemetryManager:
    def __init__(self) -> None:
        self.enabled = False
        self.service_name = "wenshu-agent"
        self.exporter = "console"
        self._tracer: Any = None
        self._meter: Any = None
        self._tracer_provider: Any = None
        self._meter_provider: Any = None
        self._spans: list[CapturedSpan] = []
        self._metrics: list[CapturedMetric] = []
        self.capture_for_tests = False
        self.query_total = _NoopInstrument()
        self.startup_total = _NoopInstrument()
        self.shutdown_total = _NoopInstrument()
        self.graceful_shutdown_total = _NoopInstrument()
        self.forced_shutdown_total = _NoopInstrument()
        self.query_success_total = _NoopInstrument()
        self.query_failed_total = _NoopInstrument()
        self.query_timeout_total = _NoopInstrument()
        self.admission_reject_total = _NoopInstrument()
        self.checkpoint_recovery_total = _NoopInstrument()
        self.cache_lookup_total = _NoopInstrument()
        self.cache_hit_total = _NoopInstrument()
        self.cache_miss_total = _NoopInstrument()
        self.exact_cache_hit_total = _NoopInstrument()
        self.semantic_cache_hit_total = _NoopInstrument()
        self.cache_write_total = _NoopInstrument()
        self.cache_write_failed_total = _NoopInstrument()
        self.cache_invalidated_total = _NoopInstrument()
        self.cache_lease_contention_total = _NoopInstrument()
        self.semantic_cache_rejected_total = _NoopInstrument()
        self.evaluation_failed_total = _NoopInstrument()
        self.regression_failed_total = _NoopInstrument()
        self.agent_route_total = _NoopInstrument()
        self.handoff_total = _NoopInstrument()
        self.agent_failure_total = _NoopInstrument()
        self.candidate_ranking_total = _NoopInstrument()
        self.candidate_rerank_total = _NoopInstrument()
        self.candidate_rerank_fallback_total = _NoopInstrument()
        self.candidate_partial_coverage_total = _NoopInstrument()
        self.candidate_disconnected_total = _NoopInstrument()
        self.budget_rejected_total = _NoopInstrument()
        self.quota_rejected_total = _NoopInstrument()
        self.load_shed_total = _NoopInstrument()
        self.model_route_total = _NoopInstrument()
        self.model_fallback_total = _NoopInstrument()
        self.cost_settlement_pending_total = _NoopInstrument()
        self.slo_violation_total = _NoopInstrument()
        self.error_budget_exhausted_total = _NoopInstrument()
        self.query_latency_seconds = _NoopInstrument()
        self.evaluation_score = _NoopInstrument()
        self.startup_time_seconds = _NoopInstrument()
        self.shutdown_time_seconds = _NoopInstrument()
        self.sql_execution_seconds = _NoopInstrument()
        self.llm_latency_seconds = _NoopInstrument()
        self.cache_lookup_latency_seconds = _NoopInstrument()
        self.embedding_latency_seconds = _NoopInstrument()
        self.semantic_search_latency_seconds = _NoopInstrument()
        self.cache_entry_age_seconds = _NoopInstrument()
        self.semantic_similarity_score = _NoopInstrument()
        self.candidate_ranking_latency_seconds = _NoopInstrument()
        self.candidate_count = _NoopInstrument()
        self.selected_candidate_count = _NoopInstrument()
        self.requirement_coverage_ratio = _NoopInstrument()
        self.selected_relationship_distance = _NoopInstrument()
        self.request_cost = _NoopInstrument()
        self.request_input_tokens = _NoopInstrument()
        self.request_output_tokens = _NoopInstrument()
        self.model_routing_latency_seconds = _NoopInstrument()
        self.budget_check_latency_seconds = _NoopInstrument()
        self.quota_check_latency_seconds = _NoopInstrument()
        self._active_queries = 0
        self._cache_lease_active = 0
        self._active_connections = 0
        self._active_graph_tasks = 0
        self._error_budget_remaining_ratio = 1.0
        self._admission_utilization = 0.0
        self._capacity_saturation_ratio = 0.0
        self._pending_cost_settlements = 0

    def init(self) -> None:
        self.enabled = bool(app_config.telemetry.enabled)
        self.service_name = app_config.telemetry.service_name
        self.exporter = app_config.telemetry.exporter
        if not self.enabled or trace is None or metrics is None:
            return
        resource = Resource.create({"service.name": self.service_name}) if Resource else None
        self._tracer_provider = TracerProvider(resource=resource)
        if self.exporter == "console" and BatchSpanProcessor and ConsoleSpanExporter:
            self._tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(self._tracer_provider)
        self._tracer = trace.get_tracer(self.service_name)
        if MeterProvider and PeriodicExportingMetricReader and ConsoleMetricExporter:
            reader = PeriodicExportingMetricReader(ConsoleMetricExporter()) if self.exporter == "console" else None
            self._meter_provider = MeterProvider(metric_readers=[reader] if reader else [], resource=resource)
            metrics.set_meter_provider(self._meter_provider)
            self._meter = metrics.get_meter(self.service_name)
            self._create_otel_instruments()

    async def shutdown(self) -> None:
        if self._tracer_provider is not None:
            self._tracer_provider.force_flush()
            self._tracer_provider.shutdown()
        if self._meter_provider is not None:
            self._meter_provider.force_flush()
            self._meter_provider.shutdown()

    def _create_otel_instruments(self) -> None:
        if self._meter is None:
            return
        self.query_total = self._meter.create_counter("query_total")
        self.startup_total = self._meter.create_counter("startup_total")
        self.shutdown_total = self._meter.create_counter("shutdown_total")
        self.graceful_shutdown_total = self._meter.create_counter("graceful_shutdown_total")
        self.forced_shutdown_total = self._meter.create_counter("forced_shutdown_total")
        self.query_success_total = self._meter.create_counter("query_success_total")
        self.query_failed_total = self._meter.create_counter("query_failed_total")
        self.query_timeout_total = self._meter.create_counter("query_timeout_total")
        self.admission_reject_total = self._meter.create_counter("admission_reject_total")
        self.checkpoint_recovery_total = self._meter.create_counter("checkpoint_recovery_total")
        self.cache_lookup_total = self._meter.create_counter("cache_lookup_total")
        self.cache_hit_total = self._meter.create_counter("cache_hit_total")
        self.cache_miss_total = self._meter.create_counter("cache_miss_total")
        self.exact_cache_hit_total = self._meter.create_counter("exact_cache_hit_total")
        self.semantic_cache_hit_total = self._meter.create_counter("semantic_cache_hit_total")
        self.cache_write_total = self._meter.create_counter("cache_write_total")
        self.cache_write_failed_total = self._meter.create_counter("cache_write_failed_total")
        self.cache_invalidated_total = self._meter.create_counter("cache_invalidated_total")
        self.cache_lease_contention_total = self._meter.create_counter("cache_lease_contention_total")
        self.semantic_cache_rejected_total = self._meter.create_counter("semantic_cache_rejected_total")
        self.evaluation_failed_total = self._meter.create_counter("evaluation_failed_total")
        self.regression_failed_total = self._meter.create_counter("regression_failed_total")
        self.agent_route_total = self._meter.create_counter("agent_route_total")
        self.handoff_total = self._meter.create_counter("handoff_total")
        self.agent_failure_total = self._meter.create_counter("agent_failure_total")
        self.candidate_ranking_total = self._meter.create_counter("candidate_ranking_total")
        self.candidate_rerank_total = self._meter.create_counter("candidate_rerank_total")
        self.candidate_rerank_fallback_total = self._meter.create_counter("candidate_rerank_fallback_total")
        self.candidate_partial_coverage_total = self._meter.create_counter("candidate_partial_coverage_total")
        self.candidate_disconnected_total = self._meter.create_counter("candidate_disconnected_total")
        self.budget_rejected_total = self._meter.create_counter("budget_rejected_total")
        self.quota_rejected_total = self._meter.create_counter("quota_rejected_total")
        self.load_shed_total = self._meter.create_counter("load_shed_total")
        self.model_route_total = self._meter.create_counter("model_route_total")
        self.model_fallback_total = self._meter.create_counter("model_fallback_total")
        self.cost_settlement_pending_total = self._meter.create_counter("cost_settlement_pending_total")
        self.slo_violation_total = self._meter.create_counter("slo_violation_total")
        self.error_budget_exhausted_total = self._meter.create_counter("error_budget_exhausted_total")
        self.query_latency_seconds = self._meter.create_histogram("query_latency_seconds")
        self.evaluation_score = self._meter.create_histogram("evaluation_score")
        self.startup_time_seconds = self._meter.create_histogram("startup_time_seconds")
        self.shutdown_time_seconds = self._meter.create_histogram("shutdown_time_seconds")
        self.sql_execution_seconds = self._meter.create_histogram("sql_execution_seconds")
        self.llm_latency_seconds = self._meter.create_histogram("llm_latency_seconds")
        self.cache_lookup_latency_seconds = self._meter.create_histogram("cache_lookup_latency_seconds")
        self.embedding_latency_seconds = self._meter.create_histogram("embedding_latency_seconds")
        self.semantic_search_latency_seconds = self._meter.create_histogram("semantic_search_latency_seconds")
        self.cache_entry_age_seconds = self._meter.create_histogram("cache_entry_age_seconds")
        self.semantic_similarity_score = self._meter.create_histogram("semantic_similarity_score")
        self.candidate_ranking_latency_seconds = self._meter.create_histogram("candidate_ranking_latency_seconds")
        self.candidate_count = self._meter.create_histogram("candidate_count")
        self.selected_candidate_count = self._meter.create_histogram("selected_candidate_count")
        self.requirement_coverage_ratio = self._meter.create_histogram("requirement_coverage_ratio")
        self.selected_relationship_distance = self._meter.create_histogram("selected_relationship_distance")
        self.request_cost = self._meter.create_histogram("request_cost")
        self.request_input_tokens = self._meter.create_histogram("request_input_tokens")
        self.request_output_tokens = self._meter.create_histogram("request_output_tokens")
        self.model_routing_latency_seconds = self._meter.create_histogram("model_routing_latency_seconds")
        self.budget_check_latency_seconds = self._meter.create_histogram("budget_check_latency_seconds")
        self.quota_check_latency_seconds = self._meter.create_histogram("quota_check_latency_seconds")

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any] | None = None) -> Iterator[None]:
        safe_attributes = self.safe_attributes(attributes or {})
        safe_attributes.setdefault("request_id", request_id_ctx_var.get())
        safe_attributes.setdefault("trace_id", trace_id_ctx_var.get())
        execution_id = execution_id_ctx_var.get()
        if execution_id != "-":
            safe_attributes.setdefault("execution_id", execution_id)
        started = time.perf_counter()
        otel_span_cm = None
        if self.enabled and self._tracer is not None:
            otel_span_cm = self._tracer.start_as_current_span(name, attributes=safe_attributes)
        try:
            if otel_span_cm is not None:
                with otel_span_cm:
                    yield
            else:
                yield
        except Exception:
            self._capture_span(name, safe_attributes, "error", started)
            raise
        else:
            self._capture_span(name, safe_attributes, "ok", started)

    def _capture_span(self, name: str, attributes: dict[str, Any], status: str, started: float) -> None:
        if not self.capture_for_tests:
            return
        self._spans.append(
            CapturedSpan(
                name=name,
                attributes=dict(attributes),
                status=status,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        )

    def safe_attributes(self, attributes: Mapping[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in attributes.items():
            key_text = str(key)
            normalized = key_text.lower()
            if key_text not in SAFE_ATTRIBUTE_KEYS and any(part in normalized for part in SENSITIVE_KEY_PARTS):
                continue
            safe_value = self._safe_attribute_value(key_text, value)
            if safe_value is not None:
                safe[key_text] = safe_value
        return safe

    def _safe_attribute_value(self, key: str, value: Any) -> Any | None:
        if value is None:
            return None
        if isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            stripped = value.strip().lower()
            if key != "sql_hash" and stripped.startswith(SQL_PREFIXES):
                return "[REDACTED]"
            return value[:500]
        if isinstance(value, list | tuple):
            return [str(item)[:200] for item in list(value)[:20]]
        return str(value)[:500]

    def increment_counter(self, name: str, value: int = 1, attributes: Mapping[str, Any] | None = None) -> None:
        safe_attributes = self.safe_attributes(attributes or {})
        instrument = getattr(self, name)
        instrument.add(value, attributes=safe_attributes)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric(name, value, safe_attributes))

    def record_histogram(self, name: str, value: int | float, attributes: Mapping[str, Any] | None = None) -> None:
        safe_attributes = self.safe_attributes(attributes or {})
        instrument = getattr(self, name)
        instrument.record(value, attributes=safe_attributes)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric(name, value, safe_attributes))

    def set_active_queries(self, value: int) -> None:
        self._active_queries = max(0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("active_queries", self._active_queries, {}))

    def set_cache_lease_active(self, value: int) -> None:
        self._cache_lease_active = max(0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("cache_lease_active", self._cache_lease_active, {}))

    def set_active_connections(self, value: int) -> None:
        self._active_connections = max(0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("active_connections", self._active_connections, {}))

    def set_active_graph_tasks(self, value: int) -> None:
        self._active_graph_tasks = max(0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("active_graph_tasks", self._active_graph_tasks, {}))

    def set_error_budget_remaining_ratio(self, value: float) -> None:
        self._error_budget_remaining_ratio = max(0.0, min(1.0, value))
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("error_budget_remaining_ratio", self._error_budget_remaining_ratio, {}))

    def set_admission_utilization(self, value: float) -> None:
        self._admission_utilization = max(0.0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("admission_utilization", self._admission_utilization, {}))

    def set_capacity_saturation_ratio(self, value: float) -> None:
        self._capacity_saturation_ratio = max(0.0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("capacity_saturation_ratio", self._capacity_saturation_ratio, {}))

    def set_pending_cost_settlements(self, value: int) -> None:
        self._pending_cost_settlements = max(0, value)
        if self.capture_for_tests:
            self._metrics.append(CapturedMetric("pending_cost_settlements", self._pending_cost_settlements, {}))

    def enable_test_capture(self) -> None:
        self.capture_for_tests = True
        self.clear_test_capture()

    def disable_test_capture(self) -> None:
        self.capture_for_tests = False
        self.clear_test_capture()

    def clear_test_capture(self) -> None:
        self._spans.clear()
        self._metrics.clear()

    @property
    def captured_spans(self) -> list[CapturedSpan]:
        return list(self._spans)

    @property
    def captured_metrics(self) -> list[CapturedMetric]:
        return list(self._metrics)


telemetry_manager = TelemetryManager()
