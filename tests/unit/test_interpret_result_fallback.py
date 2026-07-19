from types import SimpleNamespace

import pytest

from app.agent.nodes import interpret_result as interpret_result_module
from app.agent.nodes.interpret_result import build_interpretation_fallback, interpret_result


def _state(result, summary):
    return {
        "query": "查询销售额",
        "result": result,
        "result_summary": summary,
    }


def _final_event(events):
    return [event for event in events if event.get("event") == "result" and "final_answer" in event][-1]


@pytest.mark.asyncio
async def test_interpret_result_fallback_when_llm_fails_before_start(monkeypatch):
    calls = 0

    async def failing_stream(state, summary):
        nonlocal calls
        calls += 1
        raise RuntimeError("llm down")
        yield ""

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", failing_stream)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state([{"amount": 10}], {"row_count": 1, "columns": ["amount"], "sample": [{"amount": 10}]})

    result = await interpret_result(state, runtime)

    assert calls == 1
    assert result["interpretation"] == "查询结果：amount = 10。"
    assert result["final_answer"] == result["interpretation"]
    assert not any(event.get("event") == "error" for event in events)
    assert _final_event(events)["final_answer"] == result["final_answer"]


@pytest.mark.asyncio
async def test_interpret_result_fallback_when_llm_outputs_empty(monkeypatch):
    calls = 0

    async def empty_stream(state, summary):
        nonlocal calls
        calls += 1
        if False:
            yield ""

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", empty_stream)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state([{"region": "华东"}], {"row_count": 1, "columns": ["region"], "sample": [{"region": "华东"}]})

    result = await interpret_result(state, runtime)

    assert calls == 1
    assert result["final_answer"] == "查询结果：region = 华东。"
    assert _final_event(events)["final_answer"] == "查询结果：region = 华东。"


@pytest.mark.asyncio
async def test_interpret_result_fallback_when_llm_outputs_whitespace(monkeypatch):
    async def whitespace_stream(state, summary):
        yield "   "
        yield "\n"

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", whitespace_stream)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state([{"a": 1, "b": 2}], {"row_count": 1, "columns": ["a", "b"], "sample": [{"a": 1, "b": 2}]})

    result = await interpret_result(state, runtime)

    assert result["final_answer"] == "查询返回 1 行，字段包括：a、b。"
    assert _final_event(events)["final_answer"] == result["final_answer"]


@pytest.mark.asyncio
async def test_interpret_result_fallback_after_partial_token(monkeypatch):
    async def partial_stream(state, summary):
        yield "部分"
        raise RuntimeError("stream interrupted")

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", partial_stream)
    monkeypatch.setattr(interpret_result_module.app_config.agent, "token_batch_chars", 1)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state([{"amount": 10}], {"row_count": 1, "columns": ["amount"], "sample": [{"amount": 10}]})

    result = await interpret_result(state, runtime)

    assert any(event.get("answer_delta") == "部分" for event in events)
    assert not any(event.get("event") == "error" for event in events)
    assert result["final_answer"] == "查询结果：amount = 10。"
    assert _final_event(events)["final_answer"] == "查询结果：amount = 10。"


@pytest.mark.asyncio
async def test_interpret_result_empty_result_uses_fallback_without_llm(monkeypatch):
    calls = 0

    async def stream_should_not_run(state, summary):
        nonlocal calls
        calls += 1
        yield "should not run"

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", stream_should_not_run)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)

    result = await interpret_result(_state([], {"row_count": 0, "columns": [], "sample": []}), runtime)

    assert calls == 0
    assert result["final_answer"] == "查询成功，但没有返回符合条件的数据。"
    assert not any(event.get("event") == "error" for event in events)


def test_build_interpretation_fallback_rules():
    assert (
        build_interpretation_fallback({"row_count": 0, "columns": [], "sample": []})
        == "查询成功，但没有返回符合条件的数据。"
    )
    assert (
        build_interpretation_fallback({"row_count": 1, "columns": ["a", "b"], "sample": [{"a": 1, "b": 2}]})
        == "查询返回 1 行，字段包括：a、b。"
    )
    assert (
        build_interpretation_fallback({"row_count": 3, "columns": ["a", "b"], "sample": [{"a": 1}]})
        == "查询成功，共返回 3 行，字段包括：a、b。"
    )
    assert "查询结果可能因行数限制而不完整" in build_interpretation_fallback(
        {"row_count": 3, "columns": ["a"], "sample": [{"a": 1}], "query_result_truncated": True}
    )
    sample_only = build_interpretation_fallback(
        {"row_count": 3, "columns": ["a"], "sample": [{"a": 1}], "sample_truncated": True}
    )
    assert "这里只展示了部分样本行" in sample_only
    assert "查询结果可能因行数限制而不完整" not in sample_only


@pytest.mark.asyncio
async def test_interpret_result_fallback_uses_summary_not_raw_sensitive_result(monkeypatch):
    async def failing_stream(state, summary):
        raise RuntimeError("llm down")
        yield ""

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", failing_stream)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state(
        [{"mobile": "13812345678"}],
        {"row_count": 1, "columns": ["mobile"], "sample": [{"mobile": "138****5678"}]},
    )

    result = await interpret_result(state, runtime)

    encoded_events = str(events)
    assert result["final_answer"] == "查询结果：mobile = 138****5678。"
    assert "13812345678" not in encoded_events
    assert "138****5678" in encoded_events


@pytest.mark.asyncio
async def test_interpret_result_fallback_ignores_raw_rows_when_exposed(monkeypatch):
    calls = 0

    async def failing_stream(state, summary):
        nonlocal calls
        calls += 1
        raise RuntimeError("llm down")
        yield ""

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", failing_stream)
    monkeypatch.setattr(interpret_result_module.app_config.agent, "expose_raw_rows_to_client", True)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state(
        [{"mobile": "13812345678"}],
        {"row_count": 1, "columns": ["mobile"], "sample": [{"mobile": "138****5678"}]},
    )

    result = await interpret_result(state, runtime)
    final_event = _final_event(events)

    assert calls == 1
    assert final_event["final_answer"] == result["final_answer"]
    assert final_event["result_summary"] == state["result_summary"]
    assert "rows" not in final_event
    assert "raw_rows" not in final_event
    assert "13812345678" not in str(final_event)


@pytest.mark.asyncio
async def test_interpret_result_success_still_exposes_masked_rows_when_enabled(monkeypatch):
    async def success_stream(state, summary):
        yield "ok"

    monkeypatch.setattr(interpret_result_module, "_stream_llm_interpretation", success_stream)
    monkeypatch.setattr(interpret_result_module.app_config.agent, "expose_raw_rows_to_client", True)
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = _state(
        [{"mobile": "13812345678"}],
        {"row_count": 1, "columns": ["mobile"], "sample": [{"mobile": "138****5678"}]},
    )

    result = await interpret_result(state, runtime)
    final_event = _final_event(events)

    assert result["final_answer"] == "ok"
    assert final_event["rows"] == [{"mobile": "138****5678"}]
    assert "13812345678" not in str(final_event)
