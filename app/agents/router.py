from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agents.base import AgentMetadata
from app.agents.registry import AgentRegistry
from app.core.telemetry import telemetry_manager


@dataclass(frozen=True)
class TaskIntent:
    task_id: str
    query: str
    required_capability: str
    complexity: str = "LOW"


@dataclass(frozen=True)
class TargetAgent:
    name: str
    capability: str
    reason: str


class LLMRouter(Protocol):
    async def route(self, intent: TaskIntent, candidates: list[AgentMetadata]) -> TargetAgent | None: ...


class AgentRouter:
    def __init__(self, registry: AgentRegistry, llm_router: LLMRouter | None = None) -> None:
        self.registry = registry
        self.llm_router = llm_router

    async def route(self, intent: TaskIntent) -> TargetAgent | None:
        with telemetry_manager.span(
            "agent.route",
            {"resource": intent.required_capability, "decision": "rule"},
        ):
            candidates = self.registry.discover(intent.required_capability)
            if candidates:
                telemetry_manager.increment_counter("agent_route_total", attributes={"decision": "rule"})
                selected = sorted(candidates, key=lambda item: (item.risk_level, item.name))[0]
                return TargetAgent(selected.name, intent.required_capability, "rule_capability_match")
        if self.llm_router is None:
            return None
        routed = await self.llm_router.route(intent, self.registry.list_agents())
        if routed is not None:
            telemetry_manager.increment_counter("agent_route_total", attributes={"decision": "llm"})
        return routed
