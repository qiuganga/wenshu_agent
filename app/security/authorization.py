from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.telemetry import telemetry_manager
from app.security.context import SecurityContext
from app.security.policy import PolicyRule


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    decision: str
    reason: str
    resource: str
    action: str


class AuthorizationEngine:
    def __init__(
        self,
        *,
        role_permissions: dict[str, set[str]] | None = None,
        policy_rules: list[PolicyRule] | None = None,
        default_policy: str = "deny",
    ) -> None:
        self.role_permissions = role_permissions or {}
        self.policy_rules = policy_rules or []
        self.default_policy = default_policy.lower()

    def authorize(
        self,
        context: SecurityContext,
        *,
        resource: str,
        action: str,
        attributes: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        with telemetry_manager.span(
            "security.authorization",
            {
                "user_hash": context.user_hash,
                "resource": resource,
                "action": action,
            },
        ):
            return self._authorize(context, resource=resource, action=action, attributes=attributes)

    def _authorize(
        self,
        context: SecurityContext,
        *,
        resource: str,
        action: str,
        attributes: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        normalized_resource = resource.lower()
        normalized_action = action.lower()
        permissions = self._effective_permissions(context)
        for rule in self.policy_rules:
            if rule.matches(resource=normalized_resource, action=normalized_action, attributes=attributes):
                allowed = rule.effect == "allow"
                return AuthorizationDecision(
                    allowed=allowed,
                    decision="ALLOW" if allowed else "DENY",
                    reason=f"policy_{rule.effect}",
                    resource=normalized_resource,
                    action=normalized_action,
                )

        if self._has_permission(permissions, normalized_resource, normalized_action):
            return AuthorizationDecision(
                allowed=True,
                decision="ALLOW",
                reason="permission_match",
                resource=normalized_resource,
                action=normalized_action,
            )

        if self.default_policy == "allow":
            return AuthorizationDecision(
                allowed=True,
                decision="ALLOW",
                reason="default_allow",
                resource=normalized_resource,
                action=normalized_action,
            )
        return AuthorizationDecision(
            allowed=False,
            decision="DENY",
            reason="default_deny",
            resource=normalized_resource,
            action=normalized_action,
        )

    def _effective_permissions(self, context: SecurityContext) -> set[str]:
        permissions = {permission.lower() for permission in context.permissions}
        for role in context.roles:
            permissions.update(permission.lower() for permission in self.role_permissions.get(role, set()))
        return permissions

    @staticmethod
    def _has_permission(permissions: set[str], resource: str, action: str) -> bool:
        resource_type = resource.split(":", 1)[0]
        candidates = {
            "*:*",
            f"{resource}:{action}",
            f"{resource_type}:*",
            f"{resource_type}:{action}",
        }
        return bool(permissions & candidates)


authorization_engine = AuthorizationEngine()
