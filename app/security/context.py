from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

DEFAULT_QUERY_PERMISSIONS = (
    "agent:execute",
    "database:read",
    "table:read",
    "column:read",
)


@dataclass(frozen=True)
class SecurityContext:
    user_id: str
    tenant_id: str | None = None
    roles: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    data_scope: dict[str, str] = field(default_factory=dict)
    request_id: str = "-"
    trace_id: str = "-"

    @property
    def user_hash(self) -> str:
        return hashlib.sha256(self.user_id.encode("utf-8")).hexdigest()

    @property
    def tenant_or_default(self) -> str:
        return self.tenant_id or "default"

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "user_hash": self.user_hash,
            "tenant_id": self.tenant_or_default,
            "roles": list(self.roles),
            "permissions": list(self.permissions),
            "data_scope": dict(self.data_scope),
            "request_id": self.request_id,
            "trace_id": self.trace_id,
        }


def create_security_context(
    *,
    user_id: str | None,
    tenant_id: str | None = None,
    roles: list[str] | tuple[str, ...] | None = None,
    permissions: list[str] | tuple[str, ...] | None = None,
    data_scope: dict[str, str] | None = None,
    request_id: str = "-",
    trace_id: str = "-",
) -> SecurityContext:
    normalized_user = (user_id or "anonymous").strip() or "anonymous"
    normalized_tenant = (tenant_id or "").strip() or None
    active_roles = ("query_user",) if roles is None else roles
    active_permissions = DEFAULT_QUERY_PERMISSIONS if permissions is None else permissions
    normalized_roles = tuple(role.strip() for role in active_roles if role.strip())
    normalized_permissions = tuple(permission.strip() for permission in active_permissions if permission.strip())
    return SecurityContext(
        user_id=normalized_user,
        tenant_id=normalized_tenant,
        roles=normalized_roles,
        permissions=normalized_permissions,
        data_scope=dict(data_scope or {}),
        request_id=request_id,
        trace_id=trace_id,
    )
