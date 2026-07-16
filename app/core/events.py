from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    request_id: str
    event: Literal["started", "stage", "sql_generated", "sql_validated", "sql_corrected", "result", "error", "done"]
    node: str | None = None
    status: str = "ok"
    message: str
    sequence: int = Field(ge=1)
    elapsed_ms: int | None = None
    data: dict[str, Any] | None = None


def elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def format_sse(event: AgentEvent) -> str:
    payload = event.model_dump(mode="json")
    return f"event: {event.event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
