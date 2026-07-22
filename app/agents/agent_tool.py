from __future__ import annotations

from app.agents.base import AgentTask, BaseAgent
from app.security.context import SecurityContext
from app.security.tool_guard import ToolMetadata, ToolPermissionGuard, tool_permission_guard


class AgentToolAdapter:
    def __init__(self, agent: BaseAgent, guard: ToolPermissionGuard | None = None) -> None:
        self.agent = agent
        self.guard = guard or tool_permission_guard

    async def execute(self, context: SecurityContext, task: AgentTask):
        metadata = self.agent.metadata()
        decision = self.guard.check(
            context,
            ToolMetadata(
                name=metadata.name,
                description=metadata.description,
                risk_level=metadata.risk_level,
            ),
        )
        if not decision.allowed:
            return {"success": False, "error_code": "AGENT_TOOL_PERMISSION_DENIED", "reason": decision.reason}
        result = await self.agent.execute(task)
        return {"success": result.success, "agent_name": result.agent_name, "output": result.output}
