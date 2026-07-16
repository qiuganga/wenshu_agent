from __future__ import annotations

import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class NodeTrace(BaseModel):
    node: str
    started_at: datetime
    elapsed_ms: int
    status: str
    error_code: str | None = None
    input_size: int | None = None
    output_size: int | None = None


class LLMUsage(BaseModel):
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int
    estimated_cost: float | None = None


class RequestTrace(BaseModel):
    request_id: str
    total_elapsed_ms: int = 0
    node_traces: list[NodeTrace] = Field(default_factory=list)
    llm_calls: list[LLMUsage] = Field(default_factory=list)
    sql_execution_ms: int | None = None
    retry_count: int = 0
    final_status: str = "running"


request_trace_ctx: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


def estimate_size(value: Any) -> int | None:
    try:
        return len(str(value))
    except Exception:
        return None


@asynccontextmanager
async def trace_node(node: str, input_value: Any = None):
    trace = request_trace_ctx.get()
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    status = "ok"
    error_code = None
    output_value = None
    try:
        yield lambda value: globals().update(_last_trace_output=value)
    except Exception as exc:
        status = "error"
        error_code = getattr(exc, "code", type(exc).__name__)
        raise
    finally:
        if trace is not None:
            trace.node_traces.append(
                NodeTrace(
                    node=node,
                    started_at=started_at,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    status=status,
                    error_code=error_code,
                    input_size=estimate_size(input_value),
                    output_size=estimate_size(output_value),
                )
            )


def extract_llm_usage(model: str, response: Any, latency_ms: int, estimated_cost: float | None = None) -> LLMUsage:
    metadata = getattr(response, "response_metadata", {}) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    return LLMUsage(
        model=model,
        prompt_tokens=token_usage.get("prompt_tokens"),
        completion_tokens=token_usage.get("completion_tokens"),
        total_tokens=token_usage.get("total_tokens"),
        latency_ms=latency_ms,
        estimated_cost=estimated_cost,
    )
