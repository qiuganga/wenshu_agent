from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.capability import DATA_ANALYSIS, SQL_GENERATION
from app.agents.router import AgentRouter, TaskIntent
from app.core.telemetry import telemetry_manager


@dataclass(frozen=True)
class ExecutionStep:
    order: int
    capability: str
    target_agent: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    task_id: str
    steps: list[ExecutionStep] = field(default_factory=list)


class SupervisorAgent:
    name = "supervisor"
    description = "Plans multi-agent execution without directly invoking tools."

    def __init__(self, router: AgentRouter) -> None:
        self.router = router

    async def plan(self, task_id: str, query: str) -> ExecutionPlan:
        with telemetry_manager.span("agent.supervisor", {"resource": task_id}):
            capabilities = self._required_capabilities(query)
            steps: list[ExecutionStep] = []
            for index, capability in enumerate(capabilities, start=1):
                target = await self.router.route(TaskIntent(task_id, query, capability))
                steps.append(
                    ExecutionStep(
                        order=index,
                        capability=capability,
                        target_agent=target.name if target else None,
                        description=f"Run {capability}",
                    )
                )
            return ExecutionPlan(task_id, steps)

    @staticmethod
    def _required_capabilities(query: str) -> list[str]:
        normalized = query.lower()
        capabilities = [SQL_GENERATION.normalized()]
        if any(keyword in normalized for keyword in ("分析", "原因", "趋势", "trend", "why")):
            capabilities.append(DATA_ANALYSIS.normalized())
        return capabilities


async def supervisor_node(state: dict, runtime) -> dict:
    registry = runtime.context["agent_registry"]
    supervisor = SupervisorAgent(AgentRouter(registry))
    plan = await supervisor.plan(state.get("request_id") or state.get("execution_id") or "task", state.get("query", ""))
    return {"multi_agent_plan": [step.__dict__ for step in plan.steps]}
