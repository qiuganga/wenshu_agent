from __future__ import annotations

from app.agents.a2a.message import AgentMessage
from app.agents.registry import AgentRegistry


class A2AProtocol:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry

    def validate(self, message: AgentMessage) -> AgentMessage:
        if self.registry.get(message.sender) is None:
            raise ValueError("sender agent is not registered")
        receiver = self.registry.get(message.receiver)
        if receiver is None:
            raise ValueError("receiver agent is not registered")
        if message.capability.lower() not in {capability.normalized() for capability in receiver.capabilities}:
            raise ValueError("receiver does not support requested capability")
        return message.safe()
