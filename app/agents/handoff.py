from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.telemetry import telemetry_manager

FORBIDDEN_CONTEXT_KEYS = frozenset({"password", "passwd", "token", "secret", "api_key", "prompt", "raw_result"})


@dataclass(frozen=True)
class HandoffContext:
    sender: str
    receiver: str
    task_id: str
    payload: dict[str, Any]
    trace_id: str = "-"


class HandoffManager:
    def create(
        self,
        *,
        sender: str,
        receiver: str,
        task_id: str,
        payload: dict[str, Any],
        trace_id: str = "-",
    ) -> HandoffContext:
        safe_payload = sanitize_payload(payload)
        with telemetry_manager.span("agent.handoff", {"resource": receiver, "trace_id": trace_id}):
            telemetry_manager.increment_counter("handoff_total", attributes={"resource": receiver})
        return HandoffContext(sender, receiver, task_id, safe_payload, trace_id)


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in FORBIDDEN_CONTEXT_KEYS:
            continue
        if isinstance(value, dict):
            safe[str(key)] = sanitize_payload(value)
        elif isinstance(value, list):
            safe[str(key)] = [str(item)[:500] for item in value[:20]]
        elif isinstance(value, str):
            safe[str(key)] = value[:1000]
        elif isinstance(value, int | float | bool) or value is None:
            safe[str(key)] = value
        else:
            safe[str(key)] = str(value)[:500]
    return safe


handoff_manager = HandoffManager()
