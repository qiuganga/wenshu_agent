from __future__ import annotations

from app.agents.base import AgentMetadata, BaseAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        key = agent.name.strip().lower()
        if not key:
            raise ValueError("agent name must not be empty")
        self._agents[key] = agent

    def get(self, name: str) -> BaseAgent | None:
        return self._agents.get(name.strip().lower())

    def require(self, name: str) -> BaseAgent:
        agent = self.get(name)
        if agent is None:
            raise KeyError(f"agent not found: {name}")
        return agent

    def list_agents(self) -> list[AgentMetadata]:
        return [agent.metadata() for agent in self._agents.values()]

    def discover(self, capability: str) -> list[AgentMetadata]:
        normalized = capability.strip().lower()
        return [
            agent.metadata()
            for agent in self._agents.values()
            if normalized in {capability.normalized() for capability in agent.capabilities}
        ]


agent_registry = AgentRegistry()
