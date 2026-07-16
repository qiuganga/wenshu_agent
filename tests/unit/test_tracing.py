from app.core.tracing import RequestTrace, extract_llm_usage, request_trace_ctx


class FakeResponse:
    response_metadata = {"token_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}


def test_extract_llm_usage():
    usage = extract_llm_usage("model", FakeResponse(), 12)
    assert usage.prompt_tokens == 1
    assert usage.total_tokens == 3
    assert usage.latency_ms == 12


def test_request_trace_context_is_isolated():
    trace = RequestTrace(request_id="rid")
    token = request_trace_ctx.set(trace)
    try:
        assert request_trace_ctx.get() is trace
    finally:
        request_trace_ctx.reset(token)
    assert request_trace_ctx.get() is None
