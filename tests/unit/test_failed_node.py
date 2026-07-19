from types import SimpleNamespace

import pytest

from app.agent.nodes.failed import failed
from app.core.exceptions import AgentNonRetryableError, AgentRetryExceededError


@pytest.mark.asyncio
async def test_failed_node_maps_sql_cost_message_and_retry_exhausted_exception():
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = {
        "error": "SQL cost too high",
        "error_code": "SQL_COST_TOO_HIGH",
        "retryable": True,
        "retry_count": 2,
        "max_retries": 2,
    }

    with pytest.raises(AgentRetryExceededError) as exc_info:
        await failed(state, runtime)

    assert "查询范围过大" in str(exc_info.value.message)
    assert exc_info.value.details == {
        "error_code": "SQL_COST_TOO_HIGH",
        "retryable": True,
        "error_already_emitted": True,
    }
    assert events == [
        {
            "event": "error",
            "node": "failed",
            "message": "查询范围过大或执行成本过高，请缩小时间范围、减少维度或简化查询条件。",
            "code": "SQL_COST_TOO_HIGH",
            "retryable": True,
        }
    ]


@pytest.mark.asyncio
async def test_failed_node_non_retryable_uses_non_retryable_exception():
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)
    state = {
        "error": "permission denied: token=secret",
        "error_code": "PERMISSION_DENIED",
        "retryable": False,
        "retry_count": 0,
        "max_retries": 2,
        "validation_detail": "Unknown column 'x'; password=secret",
    }

    with pytest.raises(AgentNonRetryableError) as exc_info:
        await failed(state, runtime)

    assert exc_info.value.message == "当前请求无法访问所需数据。"
    assert exc_info.value.details == {
        "error_code": "PERMISSION_DENIED",
        "retryable": False,
        "error_already_emitted": True,
    }
    assert "secret" not in str(events)
    assert "validation_detail" not in str(events)
    assert events[0]["retryable"] is False


@pytest.mark.asyncio
async def test_failed_node_default_message_is_safe():
    events = []
    runtime = SimpleNamespace(stream_writer=events.append)

    with pytest.raises(AgentNonRetryableError):
        await failed({"error": "stack trace", "retry_count": 0, "max_retries": 2}, runtime)

    assert events[0]["code"] == "AGENT_FAILED"
    assert events[0]["message"] == "本次查询未能完成，请稍后重试或调整问题描述。"
