from __future__ import annotations

from dataclasses import dataclass, field

from app.security.authorization import AuthorizationDecision, AuthorizationEngine, authorization_engine
from app.security.context import SecurityContext


@dataclass(frozen=True)
class SQLAccessCheck:
    operation: str
    tables: list[str] = field(default_factory=list)
    columns: dict[str, list[str]] = field(default_factory=dict)
    database: str | None = None


@dataclass(frozen=True)
class SQLAccessResult:
    allowed: bool
    permission_decision: str
    denied_reason: str | None = None
    denied_resource: str | None = None


class SQLAccessController:
    def __init__(self, engine: AuthorizationEngine | None = None) -> None:
        self.engine = engine or authorization_engine

    def check(self, context: SecurityContext, access: SQLAccessCheck) -> SQLAccessResult:
        if access.operation.upper() != "SELECT":
            return SQLAccessResult(
                allowed=False,
                permission_decision="DENY",
                denied_reason="write_operations_are_not_allowed",
                denied_resource=f"operation:{access.operation.lower()}",
            )
        if access.database:
            database_decision = self._authorize(context, resource=f"database:{access.database}", action="read")
            if not database_decision.allowed:
                return self._deny(database_decision)
        for table in access.tables:
            table_decision = self._authorize(context, resource=f"table:{table}", action="read")
            if not table_decision.allowed:
                return self._deny(table_decision)
        for table, columns in access.columns.items():
            for column in columns:
                column_decision = self._authorize(context, resource=f"column:{table}.{column}", action="read")
                if not column_decision.allowed:
                    return self._deny(column_decision)
        return SQLAccessResult(allowed=True, permission_decision="ALLOW")

    def _authorize(self, context: SecurityContext, *, resource: str, action: str) -> AuthorizationDecision:
        return self.engine.authorize(context, resource=resource, action=action)

    @staticmethod
    def _deny(decision: AuthorizationDecision) -> SQLAccessResult:
        return SQLAccessResult(
            allowed=False,
            permission_decision="DENY",
            denied_reason=decision.reason,
            denied_resource=decision.resource,
        )


sql_access_controller = SQLAccessController()
