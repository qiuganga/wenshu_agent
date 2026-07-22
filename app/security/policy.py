from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PolicyRule:
    resource: str
    action: str
    effect: str = "allow"
    condition: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PolicyRule:
        return cls(
            resource=str(value["resource"]),
            action=str(value["action"]),
            effect=str(value.get("effect", "allow")).lower(),
            condition=dict(value.get("condition", {})),
            description=str(value.get("description", "")),
        )

    def matches(self, *, resource: str, action: str, attributes: dict[str, Any] | None = None) -> bool:
        if not _match_token(self.resource, resource):
            return False
        if not _match_token(self.action, action):
            return False
        active_attributes = attributes or {}
        return all(active_attributes.get(key) == expected for key, expected in self.condition.items())


def _match_token(pattern: str, value: str) -> bool:
    return pattern == "*" or pattern.lower() == value.lower()
