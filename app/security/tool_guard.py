from __future__ import annotations

from dataclasses import dataclass

from app.core.telemetry import telemetry_manager
from app.security.authorization import AuthorizationDecision, AuthorizationEngine, authorization_engine
from app.security.context import SecurityContext


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str = ""
    risk_level: str = "LOW"


class ToolPermissionGuard:
    def __init__(self, engine: AuthorizationEngine | None = None) -> None:
        self.engine = engine or authorization_engine

    def check(self, context: SecurityContext, tool: ToolMetadata) -> AuthorizationDecision:
        with telemetry_manager.span(
            "security.tool_check",
            {"user_hash": context.user_hash, "tool_name": tool.name, "risk_level": tool.risk_level.upper()},
        ):
            risk = tool.risk_level.upper()
            required_resource = f"tool:{tool.name.lower()}"
            decision = self.engine.authorize(
                context,
                resource=required_resource,
                action="execute",
                attributes={"risk_level": risk},
            )
            if risk == "HIGH" and f"tool:{tool.name.lower()}:execute" not in {
                permission.lower() for permission in context.permissions
            }:
                return AuthorizationDecision(
                    allowed=False,
                    decision="DENY",
                    reason="high_risk_tool_requires_explicit_permission",
                    resource=required_resource,
                    action="execute",
                )
            return decision


tool_permission_guard = ToolPermissionGuard()
