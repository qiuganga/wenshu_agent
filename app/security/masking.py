from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.telemetry import telemetry_manager
from app.security.data_masking import mask_row, mask_value


@dataclass(frozen=True)
class FieldMaskingRule:
    field_name: str
    classification: str
    mask_strategy: str = "default"


class DataMasker:
    def __init__(self, rules: list[FieldMaskingRule] | None = None) -> None:
        self.rules = {rule.field_name.lower(): rule for rule in rules or []}

    def mask_value(self, field_name: str, value: Any) -> Any:
        rule = self.rules.get(field_name.lower())
        if rule is None:
            return mask_value(field_name, value)
        if rule.classification.upper() in {"SENSITIVE", "SECRET"}:
            return mask_value(field_name, value, [field_name])
        return value

    def mask_row(self, row: dict[str, Any]) -> dict[str, Any]:
        with telemetry_manager.span("security.masking", {"masking_applied": True}):
            if not self.rules:
                return mask_row(row)
            return {key: self.mask_value(key, value) for key, value in row.items()}

    def mask_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.mask_row(row) for row in rows]


data_masker = DataMasker()
