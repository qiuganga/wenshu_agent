from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.handoff import sanitize_payload


@dataclass(frozen=True)
class AgentMessage:
    sender: str
    receiver: str
    task_id: str
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = "-"

    def safe(self) -> AgentMessage:
        return AgentMessage(
            sender=self.sender,
            receiver=self.receiver,
            task_id=self.task_id,
            capability=self.capability,
            payload=sanitize_payload(self.payload),
            trace_id=self.trace_id,
        )
