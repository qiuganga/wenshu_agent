from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agents.capability import Capability


@dataclass(frozen=True)
class AgentMetadata:
    name: str
    version: str
    capabilities: list[str]
    risk_level: str = "LOW"
    tools: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    query: str
    capability: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    agent_name: str
    output: dict[str, Any]
    success: bool = True
    error_code: str | None = None


class BaseAgent(Protocol):
    name: str
    description: str
    capabilities: list[Capability]

    def metadata(self) -> AgentMetadata: ...

    def can_handle(self, task: AgentTask) -> bool: ...

    async def execute(self, task: AgentTask) -> AgentResult: ...


class SimpleAgent:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        capabilities: list[Capability],
        version: str = "v1",
        risk_level: str = "LOW",
        tools: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.capabilities = capabilities
        self.version = version
        self.risk_level = risk_level
        self.tools = tools or []

    def metadata(self) -> AgentMetadata:
        return AgentMetadata(
            name=self.name,
            version=self.version,
            capabilities=[capability.normalized() for capability in self.capabilities],
            risk_level=self.risk_level,
            tools=list(self.tools),
            description=self.description,
        )

    def can_handle(self, task: AgentTask) -> bool:
        return task.capability.lower() in {capability.normalized() for capability in self.capabilities}

    async def execute(self, task: AgentTask) -> AgentResult:
        return AgentResult(self.name, {"task_id": task.task_id, "capability": task.capability})
