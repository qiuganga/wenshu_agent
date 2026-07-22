import pytest
from starlette.testclient import TestClient

import main
from app.core.context import request_id_ctx_var, trace_id_ctx_var
from app.core.telemetry import TelemetryManager, telemetry_manager


def test_telemetry_manager_initializes_without_optional_sdk(monkeypatch):
    manager = TelemetryManager()
    monkeypatch.setattr("app.core.telemetry.app_config.telemetry.enabled", True)
    manager.init()

    assert manager.enabled is True
    assert manager.service_name == "wenshu-agent"


def test_span_capture_includes_request_and_trace_context():
    telemetry_manager.enable_test_capture()
    request_token = request_id_ctx_var.set("rid-1")
    trace_token = trace_id_ctx_var.set("trace-1")
    try:
        with telemetry_manager.span("query_execution", {"node_name": "execute_sql"}):
            pass
    finally:
        request_id_ctx_var.reset(request_token)
        trace_id_ctx_var.reset(trace_token)

    span = telemetry_manager.captured_spans[-1]
    assert span.name == "query_execution"
    assert span.attributes["request_id"] == "rid-1"
    assert span.attributes["trace_id"] == "trace-1"
    assert span.attributes["node_name"] == "execute_sql"
    telemetry_manager.disable_test_capture()


@pytest.mark.parametrize("key", ["password", "api_key", "prompt", "raw_result", "normalized_sql"])
def test_sensitive_attribute_keys_are_filtered(key):
    manager = TelemetryManager()

    attrs = manager.safe_attributes({key: "secret", "sql_hash": "abc", "row_count": 1})

    assert key not in attrs
    assert attrs["sql_hash"] == "abc"
    assert attrs["row_count"] == 1
    assert "secret" not in str(attrs)


def test_sql_like_attribute_value_is_redacted_unless_sql_hash():
    manager = TelemetryManager()

    attrs = manager.safe_attributes({"custom": "select * from orders", "sql_hash": "select-not-sql"})

    assert attrs["custom"] == "[REDACTED]"
    assert attrs["sql_hash"] == "select-not-sql"


def test_llm_token_attributes_are_allowed_without_prompt_or_response():
    manager = TelemetryManager()

    attrs = manager.safe_attributes(
        {
            "model_name": "model-a",
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "estimated_cost": 0.01,
            "prompt": "select * from users",
            "response": "ok",
        }
    )

    assert attrs["model_name"] == "model-a"
    assert attrs["input_tokens"] == 10
    assert attrs["output_tokens"] == 5
    assert attrs["total_tokens"] == 15
    assert attrs["estimated_cost"] == 0.01
    assert "prompt" not in attrs
    assert "response" not in attrs


def test_metrics_capture_uses_safe_attributes():
    telemetry_manager.enable_test_capture()

    telemetry_manager.increment_counter("query_failed_total", attributes={"error_code": "QUERY_TOTAL_TIMEOUT"})
    telemetry_manager.record_histogram("query_latency_seconds", 0.1, attributes={"password": "secret"})

    assert [metric.name for metric in telemetry_manager.captured_metrics] == [
        "query_failed_total",
        "query_latency_seconds",
    ]
    assert "secret" not in str(telemetry_manager.captured_metrics)
    telemetry_manager.disable_test_capture()


def test_request_middleware_adds_trace_id_header():
    with TestClient(main.app) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "rid-1"})

    assert response.headers["X-Request-ID"] == "rid-1"
    assert response.headers["X-Trace-ID"]
