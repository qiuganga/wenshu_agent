from app.agents.base import AgentMetadata, SimpleAgent
from app.agents.capability import DATA_ANALYSIS, SQL_GENERATION
from app.agents.registry import AgentRegistry
from app.agents.router import AgentRouter, TargetAgent, TaskIntent


class FakeLLMRouter:
    async def route(self, intent: TaskIntent, candidates: list[AgentMetadata]) -> TargetAgent | None:
        if not candidates:
            return None
        return TargetAgent(candidates[0].name, intent.required_capability, "llm")


async def test_agent_router_prefers_rule_capability_match() -> None:
    registry = AgentRegistry()
    registry.register(SimpleAgent(name="sql_agent", description="SQL agent", capabilities=[SQL_GENERATION]))
    router = AgentRouter(registry, llm_router=FakeLLMRouter())

    target = await router.route(TaskIntent("task-1", "query", "sql_generation"))

    assert target is not None
    assert target.name == "sql_agent"
    assert target.reason == "rule_capability_match"


async def test_agent_router_falls_back_to_llm_router() -> None:
    registry = AgentRegistry()
    registry.register(SimpleAgent(name="analysis_agent", description="Analysis agent", capabilities=[DATA_ANALYSIS]))
    router = AgentRouter(registry, llm_router=FakeLLMRouter())

    target = await router.route(TaskIntent("task-1", "query", "chart_generation"))

    assert target is not None
    assert target.name == "analysis_agent"
    assert target.reason == "llm"


async def test_agent_router_returns_none_without_candidates() -> None:
    target = await AgentRouter(AgentRegistry()).route(TaskIntent("task-1", "query", "sql_generation"))

    assert target is None
